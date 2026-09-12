"""Chunk 디스패처 — StreamAccumulator + ChunkEventDispatcher.

LLM 스트림에서 오는 chunk dict를 SSE 이벤트 문자열로 변환한다.
새 chunk 타입 추가 시 _event_handlers 딕셔너리에 핸들러만 등록하면 된다.

Usage:
    acc = StreamAccumulator()
    dispatcher = ChunkEventDispatcher(stream_state, acc, user_id, conversation_id)
    async for sse_event in dispatcher.dispatch(chunk):
        yield sse_event
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from neos.api.adapters.stream_adapter import (
    StreamAdapterState,
    create_reasoning_delta_event,
    create_reasoning_done_events,
    create_reasoning_start_events,
    create_text_delta_event,
    format_done_token,
    format_sse_event,
)
from neos.api.models.open_responses import (
    ChartVizData,
    ErrorInfo,
    MermaidVizData,
    NeosArtifactDeltaEvent,
    NeosArtifactFinishEvent,
    NeosArtifactMetaEvent,
    NeosInlineVizErrorEvent,
    NeosInlineVizEvent,
    ResponseFailedEvent,
    ResponseStatus,
)
from neos.config.settings import settings as app_settings
from neos.database.connection import db_manager
from neos.learn.session_search_tool import (
    handle_search_user_sessions,
    is_session_search_tool,
)
from neos.tools.artifact_tool_handler import execute_artifact_tool
from neos.tools.inline_vis_tool_handler import execute_inline_vis_tool as execute_inline_vis_tool_fn
from neos.tools.inline_vis_tools import is_inline_vis_tool
from neos.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StreamAccumulator:
    """LLM 스트림 처리 중 누적되는 가변 상태."""

    full_content: str = ""
    artifact_info: Optional[Dict[str, Any]] = None
    inline_viz_list: List[Dict[str, Any]] = field(default_factory=list)
    usage_info: Optional[Dict[str, Any]] = None
    cost_info: Optional[Dict[str, Any]] = None
    latency_ms: Optional[float] = None
    attachment_notices: Optional[List[str]] = None


class ChunkEventDispatcher:
    """chunk["type"] → SSE 이벤트 문자열 디스패치 테이블.

    각 핸들러는 비동기 제너레이터(async generator)이며 0개 이상의 SSE 이벤트를
    yield한다. "start" chunk는 디스패치 전에 처리되어 no-op으로 처리된다.
    """

    def __init__(
        self,
        stream_state: StreamAdapterState,
        accumulator: StreamAccumulator,
        user_id: str,
        conversation_id: str,
    ) -> None:
        self._state = stream_state
        self._acc = accumulator
        self._user_id = user_id
        self._conversation_id = conversation_id

        # chunk type → async generator handler
        self._event_handlers: Dict[str, Callable] = {
            "reasoning_start": self._handle_reasoning_start,
            "reasoning": self._handle_reasoning,
            "content": self._handle_content,
            "tool_use": self._handle_tool_use,
            "complete": self._handle_complete,
            "error": self._handle_error,
        }

    async def dispatch(self, chunk: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """chunk 타입에 맞는 핸들러로 라우팅한다."""
        chunk_type = chunk.get("type", "")
        if chunk_type == "start":
            return
        handler = self._event_handlers.get(chunk_type)
        if handler is None:
            logger.warning(f"[ChunkDispatcher] Unknown chunk type: {chunk_type!r}")
            return
        async for event in handler(chunk):
            yield event

    # ------------------------------------------------------------------ #
    # Reasoning helpers
    # ------------------------------------------------------------------ #

    async def _close_reasoning_if_active(self) -> AsyncGenerator[str, None]:
        if (
            self._state.reasoning_item
            and self._state.reasoning_item.status.value == "in_progress"
        ):
            for event in create_reasoning_done_events(self._state):
                yield format_sse_event(event)

    async def _handle_reasoning_start(self, chunk: Dict) -> AsyncGenerator[str, None]:
        for event in create_reasoning_start_events(self._state):
            yield format_sse_event(event)

    async def _handle_reasoning(self, chunk: Dict) -> AsyncGenerator[str, None]:
        if not self._state.reasoning_item:
            for event in create_reasoning_start_events(self._state):
                yield format_sse_event(event)
        delta_event = create_reasoning_delta_event(self._state, chunk["content"])
        yield format_sse_event(delta_event)

    # ------------------------------------------------------------------ #
    # Content / complete / error
    # ------------------------------------------------------------------ #

    async def _handle_content(self, chunk: Dict) -> AsyncGenerator[str, None]:
        async for event in self._close_reasoning_if_active():
            yield event
        self._acc.full_content += chunk["content"]
        yield format_sse_event(create_text_delta_event(self._state, chunk["content"]))

    async def _handle_complete(self, chunk: Dict) -> AsyncGenerator[str, None]:
        async for event in self._close_reasoning_if_active():
            yield event
        self._acc.usage_info = chunk["usage"]
        self._acc.cost_info = chunk["cost"]
        self._acc.latency_ms = chunk["latency_ms"]
        self._acc.attachment_notices = chunk.get("attachment_notices")

    async def _handle_error(self, chunk: Dict) -> AsyncGenerator[str, None]:
        self._state.response.status = ResponseStatus.FAILED
        self._state.response.error = ErrorInfo(
            type="server_error",
            message=chunk.get("error", "Unknown error"),
            code=chunk.get("code"),
        )
        # format_done_token()은 pipeline이 상태 확인 후 직접 yield한다
        yield format_sse_event(ResponseFailedEvent(response=self._state.response))

    # ------------------------------------------------------------------ #
    # Tool use (3-way: inline_vis / inline_vis_disabled / artifact)
    # ------------------------------------------------------------------ #

    async def _handle_tool_use(self, chunk: Dict) -> AsyncGenerator[str, None]:
        async for event in self._close_reasoning_if_active():
            yield event

        tool_name: str = chunk.get("tool_name", "")
        tool_input: Dict = chunk.get("tool_input", {})
        logger.info(f"Tool called: {tool_name} with input: {tool_input}")

        if app_settings.INLINE_VIS_ENABLED and is_inline_vis_tool(tool_name):
            async for event in self._handle_inline_vis(tool_name, tool_input):
                yield event
        elif is_inline_vis_tool(tool_name):
            # LLM이 캐시된 system prompt로 inline vis 도구를 잘못 호출하는 경우 방어
            logger.warning(
                f"[InlineVis] {tool_name} called but INLINE_VIS_ENABLED=false. "
                "Skipping to prevent artifact handler misbehavior."
            )
        elif is_session_search_tool(tool_name):
            async for event in self._handle_session_search(tool_input):
                yield event
        else:
            async for event in self._handle_artifact(tool_name, tool_input):
                yield event

    async def _handle_session_search(
        self, tool_input: Dict
    ) -> AsyncGenerator[str, None]:
        if not app_settings.config.learn.session_search_tool:
            logger.warning(
                "[SessionSearch] search_user_sessions called but "
                "learn.session_search_tool is false. Skipping."
            )
            return
        try:
            result = await handle_search_user_sessions(
                tool_input,
                user_id=self._user_id,
                exclude_conversation_id=getattr(self, "_conversation_id", None),
            )
        except ValueError as exc:
            logger.warning("[SessionSearch] %s", exc)
            return
        snippets = result.get("snippets") or []
        if not snippets:
            text = "\n\nNo matching prior sessions."
        else:
            lines = []
            for item in snippets:
                title = (
                    item.get("conversation_title")
                    or item.get("conversation_id")
                    or ""
                )
                snippet = item.get("snippet") or ""
                prefix = f"{title}: " if title else ""
                lines.append(f"- {prefix}{snippet}")
            text = "\n\nPrior sessions:\n" + "\n".join(lines)
        self._acc.full_content += text
        yield format_sse_event(create_text_delta_event(self._state, text))

    async def _handle_inline_vis(
        self, tool_name: str, tool_input: Dict
    ) -> AsyncGenerator[str, None]:
        async for tool_event in execute_inline_vis_tool_fn(
            tool_name=tool_name, tool_input=tool_input
        ):
            event_type = tool_event.get("type")
            if event_type == "inline_viz":
                viz_type = tool_event["viz_type"]
                raw_data = tool_event["data"]
                validated_data = (
                    MermaidVizData(**raw_data)
                    if viz_type == "mermaid"
                    else ChartVizData(
                        title=raw_data["title"],
                        type=raw_data["type"],
                        data=raw_data["data"],
                    )
                )
                inline_viz_event = NeosInlineVizEvent(
                    viz_id=tool_event["viz_id"],
                    viz_type=viz_type,
                    data=validated_data,
                )
                event_dict = inline_viz_event.model_dump()
                self._acc.inline_viz_list.append({
                    "id": event_dict["viz_id"],
                    "viz_type": event_dict["viz_type"],
                    "data": event_dict["data"],
                })
                yield format_sse_event(inline_viz_event)
            elif event_type == "error":
                err_msg = tool_event.get("error", "Unknown inline visualization error")
                logger.error(f"[InlineVis] Tool error ({tool_name}): {err_msg}")
                yield format_sse_event(
                    NeosInlineVizErrorEvent(tool_name=tool_name, error=err_msg)
                )

    async def _handle_artifact(
        self, tool_name: str, tool_input: Dict
    ) -> AsyncGenerator[str, None]:
        async with await db_manager.get_session() as db_session:
            async for tool_event in execute_artifact_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                user_id=self._user_id,
                db_session=db_session,
                conversation_id=self._conversation_id,
            ):
                event_type = tool_event.get("type")
                if event_type == "artifact_meta":
                    self._acc.artifact_info = {
                        "id": tool_event.get("artifact_id"),
                        "title": tool_event.get("artifact_title"),
                        "kind": tool_event.get("artifact_kind"),
                    }
                    yield format_sse_event(NeosArtifactMetaEvent(
                        artifact_id=tool_event.get("artifact_id", ""),
                        artifact_title=tool_event.get("artifact_title", ""),
                        artifact_kind=tool_event.get("artifact_kind", "text"),
                    ))
                elif event_type == "artifact_delta":
                    yield format_sse_event(
                        NeosArtifactDeltaEvent(content=tool_event.get("content", ""))
                    )
                elif event_type == "artifact_finish":
                    yield format_sse_event(
                        NeosArtifactFinishEvent(artifact_id=tool_event.get("artifact_id"))
                    )
                elif event_type == "tool_result":
                    if not self._acc.artifact_info:
                        self._acc.full_content += f"\n\n{tool_event.get('content', '')}"
                elif event_type == "error":
                    logger.error(f"Tool execution error: {tool_event.get('error')}")
                    self._state.response.status = ResponseStatus.FAILED
                    self._state.response.error = ErrorInfo(
                        type="server_error",
                        message=tool_event.get("error", "Tool execution failed"),
                    )
                    yield format_sse_event(ResponseFailedEvent(response=self._state.response))
