"""Chat 스트림 파이프라인 — Template Method 패턴.

stream_message 핸들러의 전체 실행 흐름을 단계별로 조율한다.
각 단계는 독립적으로 테스트 가능하며, 새 단계 추가 시 run()에 삽입하면 된다.

Usage:
    pipeline = ChatStreamPipeline(...)
    async for sse_event in pipeline.run(
        conversation_id,
        request,
        current_user,
        authorized_conversation=conversation,
    ):
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
    parse_harness_progress_event,
)
from neos.api.models.open_responses import (
    ErrorInfo,
    ItemStatus,
    NeosApprovalRequestEvent,
    NeosDeepAnalysisStartedEvent,
    NeosUIFrameEvent,
    NeosWorkflowProgressEvent,
    OutputItemDoneEvent,
    ResponseFailedEvent,
    ResponseStatus,
)
from neos.api.services.chat_chunk_dispatcher import ChunkEventDispatcher, StreamAccumulator
from neos.api.services.chat_stream_strategy import resolve_llm_strategy
from neos.api.services.chat_system_prompt_builder import SystemPromptBuilder
from neos.config.model_config import is_user_selectable_model, model_config
from neos.config.model_identity import RemapCycleError, canonicalize
from neos.config.settings import settings as app_settings
from neos.utils.logger import get_logger

logger = get_logger(__name__)


async def resolve_authorized_parent_message(
    chat_service_cls,
    parent_message_id: Optional[str],
    authorized_conversation: dict[str, Any],
    current_user,
) -> Optional[dict[str, Any]]:
    """Resolve a parent message only when it belongs to the authorized owner scope."""
    if parent_message_id is None:
        return None

    parent_message = await chat_service_cls.get_message(parent_message_id)
    if not parent_message or parent_message.get("message_id") != parent_message_id:
        return None

    parent_conversation_id = parent_message.get("conversation_id")
    if not parent_conversation_id:
        return None

    parent_conversation = await chat_service_cls.get_conversation(
        parent_conversation_id
    )
    if (
        not parent_conversation
        or parent_conversation.get("user_id") != current_user.user_id
        or authorized_conversation.get("user_id") != current_user.user_id
        or parent_conversation_id
        != authorized_conversation.get("conversation_id")
    ):
        return None

    return parent_message


def resolve_turn_model_name(
    request_metadata: Dict[str, Any],
    conversation: Dict[str, Any],
) -> Optional[str]:
    """이 턴에 쓸 모델명을 고른다.

    `request_metadata["model"]`은 매 메시지 FE 셀렉터 값이 실려 오는,
    사용자가 통제하는 값이 모델 라우팅에 도달하는 경로다(#6). 요청
    오버라이드만 `canonicalize(..., apply_remap=True)` 한 뒤 selectable
    게이트를 통과한다. 저장된 `conversation["model_name"]`은 리맵하지
    않는다. 이 함수는 두 가지를 거부하고 `conversation["model_name"]`으로
    떨어진다 — 조용히가 아니라 `logger.warning`을 남기고:

    1. 문자열이 아닌 값 (`metadata`는 `Dict[str, Any]`라 list/dict가 올 수
       있다 — 그대로 카탈로그 조회에 넘기면 `dict.get()`이 해시 불가능한
       키에 `TypeError`를 내고, 그게 바깥 `except Exception`까지 번져
       턴 전체가 `response.failed`로 죽는다. 절대 그 지점까지 가면 안 된다).
    2. 사용자가 선택할 수 없는 모델
       (`neos.config.model_config.is_user_selectable_model` 참고 —
       카탈로그 *멤버*인 것과 *선택 가능*한 것은 다르다).

    설계 결정: 이 오버라이드는 **그 턴에만** 적용되고
    `conversation["model_name"]`에는 쓰이지 않는다. FE 셀렉터는
    `chat-model` 쿠키 기반 전역 기본값이라 대화별 상태가 아니기 때문이다.
    """
    requested_model = request_metadata.get("model")
    conversation_model = conversation.get("model_name")
    if not requested_model:
        return conversation_model
    if not isinstance(requested_model, str):
        logger.warning(
            "Ignoring non-string per-turn model override %r (type %s); "
            "falling back to conversation model %r",
            requested_model,
            type(requested_model).__name__,
            conversation_model,
        )
        return conversation_model
    try:
        identity = canonicalize(
            requested_model,
            catalog=model_config.catalog,
            apply_remap=True,
        )
    except RemapCycleError:
        identity = None
    pin = identity.catalog_id if identity is not None else None
    if pin is None or not is_user_selectable_model(pin):
        logger.warning(
            "Ignoring unknown or non-selectable per-turn model override %r "
            "(not in the user-selectable model catalog neos/config/models.yaml) "
            "— falling back to conversation model %r",
            requested_model,
            conversation_model,
        )
        return conversation_model
    return pin


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
        *,
        authorized_conversation: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """stream_message 의 전체 실행 흐름 — Template Method."""
        acc = StreamAccumulator()
        stream_state: Optional[StreamAdapterState] = None

        if (
            authorized_conversation.get("conversation_id") != conversation_id
            or authorized_conversation.get("user_id") != current_user.user_id
        ):
            logger.warning("Rejected chat stream owner mismatch")
            state, _ = create_stream_generator(
                response_id=conversation_id,
                message_id=str(uuid.uuid4()),
            )
            state.response.status = ResponseStatus.FAILED
            state.response.error = ErrorInfo(
                type="not_found",
                message="Resource not found",
            )
            yield format_sse_event(ResponseFailedEvent(response=state.response))
            yield format_done_token()
            return

        authorized_parent_message = await resolve_authorized_parent_message(
            self._ChatService,
            request.parent_message_id,
            authorized_conversation,
            current_user,
        )
        if (
            request.parent_message_id is not None
            and authorized_parent_message is None
        ):
            logger.warning("Rejected chat stream parent message mismatch")
            state, _ = create_stream_generator(
                response_id=conversation_id,
                message_id=str(uuid.uuid4()),
            )
            state.response.status = ResponseStatus.FAILED
            state.response.error = ErrorInfo(
                type="not_found",
                message="Resource not found",
            )
            yield format_sse_event(ResponseFailedEvent(response=state.response))
            yield format_done_token()
            return

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
            conversation = authorized_conversation
            turn_model_name = resolve_turn_model_name(request_metadata, conversation)
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
                .with_session_search()
                .build()
            )

            # ── Step 6: LLM 전략 선택 + 스트리밍 ─────────────────────
            strategy = await resolve_llm_strategy(
                chat_llm_service=self._llm_svc,
                get_core_tools_fn=self._get_core_tools_fn,
                get_search_handler_fn=self._get_search_handler_fn,
            )
            # history_messages는 이미 방금 Step 1에서 저장한 유저 턴으로 끝난다
            # (tail 조회이므로) — 여기서 다시 append하면 중복된다.
            messages = history_messages
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
                model_name=turn_model_name,
                system_prompt=system_prompt,
                temperature=conversation.get("temperature", 0.7),
                max_tokens=conversation.get("max_tokens"),
                tools=tools,
                user_id=current_user.user_id,
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
            if acc.attachment_notices:
                message_metadata["attachment_notices"] = acc.attachment_notices
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
                model_name=turn_model_name,
                total_tokens=acc.usage_info["total_tokens"] if acc.usage_info else 0,
                prompt_tokens=acc.usage_info["prompt_tokens"] if acc.usage_info else 0,
                completion_tokens=acc.usage_info["completion_tokens"] if acc.usage_info else 0,
                metadata=message_metadata,
            )

            # ── Step 8: 비용 기록 (메시지 저장 후 — FK 제약 위반 방지) ─
            if acc.usage_info and acc.cost_info:
                provider = (
                    "anthropic"
                    if "claude" in (turn_model_name or "").lower()
                    else "openai"
                )
                await self._cost_calc.record_cost_for_existing_message(
                    message_id=assistant_message_id,
                    conversation_id=conversation_id,
                    provider=provider,
                    model_name=turn_model_name,
                    prompt_tokens=acc.usage_info["prompt_tokens"],
                    completion_tokens=acc.usage_info["completion_tokens"],
                    total_tokens=acc.usage_info["total_tokens"],
                    latency_ms=acc.latency_ms,
                    finish_reason="end_turn",
                    cache_creation_tokens=acc.usage_info.get(
                        "cache_creation_tokens", 0
                    ),
                    cache_read_tokens=acc.usage_info.get("cache_read_tokens", 0),
                    cache_ttl=app_settings.config.llm.prompt_caching.ttl,
                    additional_cost_usd=acc.cost_info.get("additional_cost", 0),
                    metadata={
                        "anthropic": acc.usage_info.get("anthropic", {})
                    },
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
                # `history_messages`는 오름차순 tail 조회라 방금 저장한 현재 유저
                # 턴이 마지막 원소다(run() Step 1/3 참고). 그 턴은 `query`가
                # 이미 나르므로 여기서 다시 넣으면 워크플로우가 같은 턴을 두 번
                # 본다 — ce12b080이 LLM 메시지 배열에서 고친 것과 같은 모양이다.
                prior_messages = history_messages[:-1]
                # "최근 N개"가 의도이므로 tail의 **끝**에서 잘라야 한다.
                # 오름차순 순서는 그대로 유지한다(소비자가 시간순을 가정한다).
                max_history = app_settings.MAX_HISTORY_MESSAGES
                recent_messages = (
                    prior_messages[-max_history:] if max_history > 0 else []
                )
                formatted_history = [
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                        "timestamp": msg.get("created_at"),
                    }
                    for msg in recent_messages
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
                        # 하네스 노드의 진행은 JSON 페이로드를 content에 실어 보낸다.
                        # 그것을 `neos:harness`로 풀어주지 않으면 프론트의
                        # 하네스 카드가 켜지지 않고, 날 JSON이 진행 메시지로 샌다.
                        #
                        # ⚠️ `on_node_progress`는 `agent_progress`로 발행한다
                        # (`workflow_stream_handlers.py:202`). `node_progress`를
                        # 기다리면 영원히 오지 않는다 — 그 이름은 DB 로깅용이다.
                        harness_event = parse_harness_progress_event(
                            node_name=event.node_name,
                            message=event.content,
                        )
                        if harness_event is not None:
                            yield format_sse_event(harness_event)
                        else:
                            yield format_sse_event(NeosWorkflowProgressEvent(
                                progress_percent=event.progress_percent,
                                message=event.content if event.content else None,
                            ))

                    elif event.event == "ui_frame":
                        yield format_sse_event(NeosUIFrameEvent(
                            ui_frame=event.data.get("ui_frame", {})
                        ))

                    # Phase 3b (D23): deep analysis job 핸들 → 챗 SSE.
                    # 이 이벤트가 유실되면 job은 돌면서 과금되지만 프론트는
                    # run_id를 몰라 `GET /{run_id}/events`를 열지 못한다.
                    # 챗 턴 자체는 여기서 멈추지 않는다 — 진행은 전용 스트림이 나른다.
                    elif event.event == "deep_analysis_started":
                        yield format_sse_event(NeosDeepAnalysisStartedEvent(
                            run_id=event.data.get("run_id", ""),
                            events_url=event.data.get("events_url", ""),
                            assistant_message_id=event.data.get(
                                "assistant_message_id"
                            ),
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
