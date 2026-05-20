"""Chat 스트림 파이프라인 — Template Method 패턴.

stream_message 핸들러의 전체 실행 흐름을 단계별로 조율한다.
각 단계는 독립적으로 테스트 가능하며, 새 단계 추가 시 run()에 삽입하면 된다.

Usage:
    pipeline = ChatStreamPipeline(...)
    async for sse_event in pipeline.run(conversation_id, request, current_user):
        yield sse_event
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Coroutine, Dict, List, Optional

from neos.api.adapters.stream_adapter import (
    StreamAdapterState,
    create_completed_event,
    create_function_call_event,
    create_stream_generator,
    format_done_token,
    format_sse_event,
)
from neos.api.models.open_responses import (
    ErrorInfo,
    ItemStatus,
    NeosApprovalRequestEvent,
    NeosUIFrameEvent,
    NeosWorkflowProgressEvent,
    OutputItemDoneEvent,
    ResponseFailedEvent,
    ResponseStatus,
)
from neos.api.services.chat_chunk_dispatcher import ChunkEventDispatcher, StreamAccumulator
from neos.api.services.chat_stream_strategy import resolve_llm_strategy
from neos.api.services.chat_system_prompt_builder import SystemPromptBuilder
from neos.config.settings import settings as app_settings
from neos.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _WorkflowCtx:
    """_run_workflow() → run() 간 결과 전달용 컨테이너."""

    result: Optional[Dict[str, Any]] = None
    agents: List[Dict[str, Any]] = field(default_factory=list)
    approval_requests: List[Dict[str, Any]] = field(default_factory=list)


class ChatStreamPipeline:
    """stream_message의 전체 실행 흐름을 단계별로 조율하는 파이프라인.

    의존 객체를 생성자에서 주입받아 테스트 가능성을 높인다.
    """

    def __init__(
        self,
        chat_llm_service,
        cost_calculator,
        get_core_tools_fn: Callable[[], Coroutine],
        get_search_handler_fn: Callable,
        chat_service_cls,
        multi_agent_workflow,
        workflow_callback_cls,
        map_node_to_agent_fn: Callable[[str], str],
    ) -> None:
        self._llm_svc = chat_llm_service
        self._cost_calc = cost_calculator
        self._get_core_tools_fn = get_core_tools_fn
        self._get_search_handler_fn = get_search_handler_fn
        self._ChatService = chat_service_cls
        self._workflow = multi_agent_workflow
        self._WorkflowCallback = workflow_callback_cls
        self._map_node = map_node_to_agent_fn

    async def run(
        self,
        conversation_id: str,
        request,   # SendMessageRequest
        current_user,  # User
    ) -> AsyncGenerator[str, None]:
        """stream_message 의 전체 실행 흐름 — Template Method."""
        acc = StreamAccumulator()
        stream_state: Optional[StreamAdapterState] = None

        try:
            request_metadata = request.metadata or {}
            # ── Step 1: 사용자 메시지 저장 ─────────────────────────────
            await self._ChatService.add_message(
                conversation_id=conversation_id,
                role=request.role.value,
                content=request.content,
                attachments=request.attachments,
                parent_message_id=request.parent_message_id,
                metadata=request.metadata,
            )

            # ── Step 2: 스트림 초기화 ──────────────────────────────────
            assistant_message_id = str(uuid.uuid4())
            stream_state, start_event = create_stream_generator(
                response_id=conversation_id,
                message_id=assistant_message_id,
            )
            yield format_sse_event(start_event)

            # ── Step 3: 대화 정보 및 히스토리 로드 ───────────────────
            conversation = await self._ChatService.get_conversation(conversation_id)
            history_messages = await self._ChatService.get_conversation_messages(
                conversation_id=conversation_id,
                limit=20,
            )

            # ── Step 4: 워크플로우 실행 ────────────────────────────────
            wf_ctx = _WorkflowCtx()
            if app_settings.ENABLE_WORKFLOW_IN_CHAT:
                async for event in self._run_workflow(
                    conversation_id=conversation_id,
                    user_content=request.content,
                    current_user=current_user,
                    history_messages=history_messages,
                    stream_state=stream_state,
                    wf_ctx=wf_ctx,
                    autonomy_level=request_metadata.get("autonomy_level"),
                    workflow_preferences=request_metadata,
                ):
                    yield event
                if wf_ctx.result and wf_ctx.result.get("interrupted"):
                    await self._ChatService.add_message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content="",
                        message_id=assistant_message_id,
                        model_name=conversation.get("model_name"),
                        total_tokens=0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        metadata={
                            "responseStatus": "incomplete",
                            "approval_requests": wf_ctx.approval_requests,
                            "approval_session_id": conversation_id,
                        },
                    )
                    yield format_done_token()
                    return

            # ── Step 5: 시스템 프롬프트 + 도구 목록 구성 ─────────────
            system_prompt, tools = (
                SystemPromptBuilder(base=conversation.get("system_prompt", ""))
                .with_workflow_result(wf_ctx.result)
                .with_artifacts()
                .with_inline_vis()
                .build()
            )

            # ── Step 6: LLM 전략 선택 + 스트리밍 ─────────────────────
            strategy = await resolve_llm_strategy(
                chat_llm_service=self._llm_svc,
                get_core_tools_fn=self._get_core_tools_fn,
                get_search_handler_fn=self._get_search_handler_fn,
            )
            messages = history_messages + [{"role": "user", "content": request.content}]
            dispatcher = ChunkEventDispatcher(
                stream_state=stream_state,
                accumulator=acc,
                user_id=current_user.user_id,
                conversation_id=conversation_id,
            )
            llm_stream = strategy.create_stream(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                messages=messages,
                model_name=conversation.get("model_name"),
                system_prompt=system_prompt,
                temperature=conversation.get("temperature", 0.7),
                max_tokens=conversation.get("max_tokens"),
                tools=tools,
            )
            async for chunk in llm_stream:
                async for sse_event in dispatcher.dispatch(chunk):
                    yield sse_event

            # error chunk 처리 시 stream_state.response.status가 FAILED로 변경됨
            if (
                stream_state.response
                and stream_state.response.status == ResponseStatus.FAILED
            ):
                yield format_done_token()
                return

            # ── Step 7: 어시스턴트 메시지 저장 ────────────────────────
            message_metadata: Dict[str, Any] = {
                "cost_usd": float(acc.cost_info["total_cost"]) if acc.cost_info else 0.0,
                "latency_ms": acc.latency_ms,
            }
            if acc.artifact_info:
                message_metadata["artifact"] = acc.artifact_info
            if acc.inline_viz_list:
                message_metadata["inline_visualizations"] = acc.inline_viz_list
            if wf_ctx.agents:
                message_metadata["workflow_agents"] = wf_ctx.agents
            workflow_metadata = (wf_ctx.result or {}).get("metadata") or {}
            if workflow_metadata.get("mission_id"):
                message_metadata["mission"] = {
                    "mission_id": workflow_metadata.get("mission_id"),
                    "mission_status": workflow_metadata.get("mission_status"),
                    "validation_summary": workflow_metadata.get("validation_summary"),
                    "mission_plan_summary": workflow_metadata.get(
                        "mission_plan_summary"
                    ),
                }

            await self._ChatService.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=acc.full_content,
                message_id=assistant_message_id,
                model_name=conversation.get("model_name"),
                total_tokens=acc.usage_info["total_tokens"] if acc.usage_info else 0,
                prompt_tokens=acc.usage_info["prompt_tokens"] if acc.usage_info else 0,
                completion_tokens=acc.usage_info["completion_tokens"] if acc.usage_info else 0,
                metadata=message_metadata,
            )

            # ── Step 8: 비용 기록 (메시지 저장 후 — FK 제약 위반 방지) ─
            if acc.usage_info and acc.cost_info:
                provider = (
                    "anthropic"
                    if "claude" in (conversation.get("model_name") or "").lower()
                    else "openai"
                )
                await self._cost_calc.record_cost_for_existing_message(
                    message_id=assistant_message_id,
                    conversation_id=conversation_id,
                    provider=provider,
                    model_name=conversation.get("model_name"),
                    prompt_tokens=acc.usage_info["prompt_tokens"],
                    completion_tokens=acc.usage_info["completion_tokens"],
                    total_tokens=acc.usage_info["total_tokens"],
                    latency_ms=acc.latency_ms,
                    finish_reason="end_turn",
                )

            # ── Step 9: response.completed + [DONE] ──────────────────
            completed_event = create_completed_event(
                stream_state,
                usage={
                    "prompt_tokens": acc.usage_info["prompt_tokens"] if acc.usage_info else 0,
                    "completion_tokens": acc.usage_info["completion_tokens"] if acc.usage_info else 0,
                },
            )
            yield format_sse_event(completed_event)
            yield format_done_token()

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            if stream_state and stream_state.response:
                stream_state.response.status = ResponseStatus.FAILED
                stream_state.response.error = ErrorInfo(
                    type="server_error",
                    message=str(e),
                )
                yield format_sse_event(ResponseFailedEvent(response=stream_state.response))
            yield format_done_token()

    # ------------------------------------------------------------------ #
    # Workflow execution
    # ------------------------------------------------------------------ #

    async def _run_workflow(
        self,
        conversation_id: str,
        user_content: str,
        current_user,
        history_messages: List[Dict],
        stream_state: StreamAdapterState,
        wf_ctx: _WorkflowCtx,
        autonomy_level: Optional[int] = None,
        workflow_preferences: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """워크플로우를 실행하고 SSE 이벤트를 yield한다. 결과는 wf_ctx에 저장한다."""
        try:
            event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
            workflow_callback = self._WorkflowCallback(
                session_id=conversation_id,
                event_queue=event_queue,
                enable_db_logging=False,
                user_id=current_user.user_id,
            )

            formatted_history: List[Dict] = []
            if app_settings.CHAT_HISTORY_ENABLED and history_messages:
                formatted_history = [
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                        "timestamp": msg.get("created_at"),
                    }
                    for msg in history_messages[: app_settings.MAX_HISTORY_MESSAGES]
                ]
                logger.info(
                    f"[ChatPipeline] Passing {len(formatted_history)} history messages to workflow"
                )

            workflow_task = asyncio.create_task(
                self._workflow.execute_workflow(
                    user_input={
                        "user_id": current_user.user_id,
                        "session_id": conversation_id,
                        "query": user_content,
                        "chat_history": formatted_history,
                        "enable_history_context": True,
                        "autonomy_level": autonomy_level,
                        "preferences": workflow_preferences or {},
                    },
                    event_handler=workflow_callback,
                    use_checkpointer=True,
                )
            )

            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.5)

                    if event.event == "node_started":
                        agent_name = self._map_node(event.node_name)
                        wf_ctx.agents.append({
                            "agent_name": agent_name,
                            "node_name": event.node_name,
                            "status": "input-available",
                        })
                        yield format_sse_event(
                            create_function_call_event(stream_state, event.node_name, agent_name)
                        )

                    elif event.event == "node_completed":
                        for agent in wf_ctx.agents:
                            if agent["node_name"] == event.node_name:
                                agent["status"] = "output-available"
                        if event.node_name in stream_state.function_calls:
                            fc = stream_state.function_calls[event.node_name]
                            fc.status = ItemStatus.COMPLETED
                            yield format_sse_event(OutputItemDoneEvent(
                                output_index=stream_state.output_index,
                                item=fc,
                            ))

                    elif event.event == "agent_progress":
                        yield format_sse_event(NeosWorkflowProgressEvent(
                            progress_percent=event.progress_percent,
                            message=event.content if event.content else None,
                        ))

                    elif event.event == "ui_frame":
                        yield format_sse_event(NeosUIFrameEvent(
                            ui_frame=event.data.get("ui_frame", {})
                        ))

                    elif event.event == "approval_request":
                        pending_approvals = event.data.get("pending_approvals", [])
                        wf_ctx.approval_requests = pending_approvals
                        yield format_sse_event(NeosApprovalRequestEvent(
                            session_id=conversation_id,
                            pending_approvals=pending_approvals,
                        ))
                        wf_ctx.result = await workflow_task
                        break

                    elif event.event == "completed":
                        wf_ctx.result = await workflow_task
                        break

                except asyncio.TimeoutError:
                    if workflow_task.done():
                        wf_ctx.result = await workflow_task
                        break

        except Exception as e:
            import traceback
            logger.error(f"Workflow execution failed: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            logger.warning("Falling back to direct LLM.")
            wf_ctx.result = None
