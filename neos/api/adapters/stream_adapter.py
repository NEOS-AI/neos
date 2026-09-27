"""
OpenResponses Stream Adapter

Converts legacy Neos SSE events to OpenResponses specification format.
Provides bidirectional conversion and streaming support.
"""

from typing import Any, Dict, List, Optional, Generator
import uuid
import time
import json

from neos.api.models.open_responses import (
    # Response and Items
    ResponseObject,
    ResponseStatus,
    MessageItem,
    FunctionCallItem,
    ReasoningItem,
    OutputTextPart,
    UsageInfo,
    ErrorInfo,
    ItemStatus,
    # Standard Events
    ResponseInProgressEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    OutputItemAddedEvent,
    OutputItemDoneEvent,
    OutputTextDeltaEvent,
    ReasoningContentDeltaEvent,
    ReasoningContentDoneEvent,
    # Neos Extension Events
    NeosArtifactMetaEvent,
    NeosArtifactDeltaEvent,
    NeosArtifactFinishEvent,
    NeosWorkflowProgressEvent,
    NeosHarnessEvent,
    NeosUIFrameEvent,
    NeosDeepAnalysisStartedEvent,
    NeosGraphSubagentEvent,
    # Types
    OpenResponsesEvent,
    create_response,
    map_error_type,
)


class StreamAdapterState:
    """
    Maintains state during SSE stream adaptation

    Tracks the current response, message item, and function calls
    to properly generate OpenResponses events.
    """

    def __init__(self):
        self.response: Optional[ResponseObject] = None
        self.message_item: Optional[MessageItem] = None
        self.reasoning_item: Optional[ReasoningItem] = None
        self.function_calls: Dict[str, FunctionCallItem] = {}
        self.output_index: int = 0
        self.reasoning_content: str = ""
        self.started: bool = False

    def reset(self):
        """Reset state for a new stream"""
        self.__init__()


def adapt_legacy_event(
    legacy_event: Dict[str, Any],
    state: StreamAdapterState
) -> List[OpenResponsesEvent]:
    """
    Convert a legacy Neos SSE event to OpenResponses events

    Args:
        legacy_event: The legacy event dict (from ChatStreamChunk)
        state: Current adapter state

    Returns:
        List of OpenResponses events (may be empty or multiple)
    """
    event_type = legacy_event.get("type", "")
    events: List[OpenResponsesEvent] = []

    # ================================================================
    # start -> response.in_progress
    # ================================================================
    if event_type == "start":
        response_id = legacy_event.get("conversation_id", str(uuid.uuid4()))
        message_id = legacy_event.get("message_id", str(uuid.uuid4()))

        # Create response and message item
        state.response = create_response(response_id, message_id)
        state.message_item = state.response.output[0] if state.response.output else None
        state.started = True

        events.append(ResponseInProgressEvent(response=state.response))

    # ================================================================
    # content -> response.output_text.delta
    # ================================================================
    elif event_type == "content":
        if state.message_item:
            delta = legacy_event.get("content", "")

            # Update message item content
            state.message_item.add_text(delta)

            events.append(OutputTextDeltaEvent(
                item_id=state.message_item.id,
                output_index=0,
                content_index=0,
                delta=delta
            ))

    # ================================================================
    # workflow_node_start -> response.output_item.added (function_call)
    # ================================================================
    elif event_type == "workflow_node_start":
        node_name = legacy_event.get("node_name", "")
        agent_name = legacy_event.get("agent_name", node_name)

        # Create function call item
        fc_id = f"fc_{node_name}_{int(time.time() * 1000)}"
        function_call = FunctionCallItem(
            id=fc_id,
            call_id=node_name,
            name=agent_name,
            arguments="{}",
            status=ItemStatus.IN_PROGRESS
        )

        state.function_calls[node_name] = function_call
        state.output_index += 1

        events.append(OutputItemAddedEvent(
            output_index=state.output_index,
            item=function_call
        ))

    # ================================================================
    # workflow_node_complete -> response.output_item.done (function_call)
    # ================================================================
    elif event_type == "workflow_node_complete":
        node_name = legacy_event.get("node_name", "")

        if node_name in state.function_calls:
            function_call = state.function_calls[node_name]
            function_call.status = ItemStatus.COMPLETED

            events.append(OutputItemDoneEvent(
                output_index=state.output_index,
                item=function_call
            ))

    # ================================================================
    # workflow_progress -> neos:workflow_progress (extension)
    # ================================================================
    elif event_type == "workflow_progress":
        progress = legacy_event.get("progress_percent", 0)
        message = legacy_event.get("metadata", {}).get("message", "")
        harness_event = parse_harness_progress_event(
            node_name=legacy_event.get("node_name"),
            message=message,
        )
        if harness_event is not None:
            events.append(harness_event)
            return events

        events.append(NeosWorkflowProgressEvent(
            progress_percent=progress,
            message=message if message else None
        ))

    # ================================================================
    # hyper_deep_phase_start -> response.output_item.added (function_call, in_progress)
    # ================================================================
    elif event_type == "hyper_deep_phase_start":
        node_name = legacy_event.get("node_name", "")
        phase_name = legacy_event.get("data", {}).get("phase_name", "")

        fc_id = f"fc_hdr_{node_name}_{int(time.time() * 1000)}"
        function_call = FunctionCallItem(
            id=fc_id,
            call_id=node_name,
            name=node_name,
            arguments=json.dumps({"phase": phase_name}, ensure_ascii=False),
            status=ItemStatus.IN_PROGRESS,
        )

        state.function_calls[node_name] = function_call
        state.output_index += 1

        events.append(OutputItemAddedEvent(
            output_index=state.output_index,
            item=function_call,
        ))

    # ================================================================
    # hyper_deep_phase_complete -> response.output_item.done (function_call, completed)
    # ================================================================
    elif event_type == "hyper_deep_phase_complete":
        node_name = legacy_event.get("node_name", "")

        if node_name in state.function_calls:
            function_call = state.function_calls[node_name]
            function_call.status = ItemStatus.COMPLETED

            events.append(OutputItemDoneEvent(
                output_index=state.output_index,
                item=function_call,
            ))

    # ================================================================
    # hyper_deep_usage -> ResponseObject.usage 업데이트
    # ================================================================
    elif event_type == "hyper_deep_usage":
        estimated_tokens = legacy_event.get("data", {}).get("estimated_total_tokens", 0)
        if state.response and estimated_tokens:
            current_output = state.response.usage.output_tokens if state.response.usage else 0
            state.response.usage = UsageInfo(
                input_tokens=0,
                output_tokens=current_output + estimated_tokens,
            )
        # 이벤트를 별도로 emit하지 않음 — complete 이벤트 시 usage가 response에 포함됨

    # ================================================================
    # artifact_meta -> neos:artifact_meta (extension)
    # ================================================================
    elif event_type == "artifact_meta":
        events.append(NeosArtifactMetaEvent(
            artifact_id=legacy_event.get("artifact_id", ""),
            artifact_title=legacy_event.get("artifact_title", ""),
            artifact_kind=legacy_event.get("artifact_kind", "text")
        ))

    # ================================================================
    # artifact_delta -> neos:artifact_delta (extension)
    # ================================================================
    elif event_type == "artifact_delta":
        events.append(NeosArtifactDeltaEvent(
            content=legacy_event.get("content", "")
        ))

    # ================================================================
    # artifact_finish -> neos:artifact_finish (extension)
    # ================================================================
    elif event_type == "artifact_finish":
        events.append(NeosArtifactFinishEvent(
            artifact_id=legacy_event.get("artifact_id")
        ))

    # ================================================================
    # ui_frame -> neos:ui_frame (Phase 8 A2UI extension)
    # ================================================================
    elif event_type == "ui_frame":
        ui_frame_data = (
            legacy_event.get("data", {}).get("ui_frame")
            or legacy_event.get("ui_frame")
            or {}
        )
        events.append(NeosUIFrameEvent(ui_frame=ui_frame_data))

    # ================================================================
    # deep_analysis_started -> neos:deep_analysis_started (Phase 3b, D23)
    # ================================================================
    elif event_type == "deep_analysis_started":
        data = legacy_event.get("data", {}) or {}
        events.append(NeosDeepAnalysisStartedEvent(
            run_id=data.get("run_id", ""),
            events_url=data.get("events_url", ""),
            assistant_message_id=data.get("assistant_message_id"),
        ))

    # ================================================================
    # complete -> response.completed
    # ================================================================
    elif event_type == "complete":
        if state.response:
            # Update status
            state.response.status = ResponseStatus.COMPLETED

            # Update message item status
            if state.message_item:
                state.message_item.status = ItemStatus.COMPLETED

            # Add usage info if available
            metadata = legacy_event.get("metadata", {})
            if metadata.get("total_tokens"):
                state.response.usage = UsageInfo(
                    input_tokens=0,  # Not available in legacy format
                    output_tokens=metadata.get("total_tokens", 0)
                )

            # Add function calls to output
            for fc in state.function_calls.values():
                if fc not in state.response.output:
                    state.response.output.append(fc)

            events.append(ResponseCompletedEvent(response=state.response))

    # ================================================================
    # error -> response.failed
    # ================================================================
    elif event_type == "error":
        if state.response is None:
            # Create a minimal response for error
            state.response = ResponseObject(
                id=legacy_event.get("conversation_id", str(uuid.uuid4())),
                status=ResponseStatus.FAILED,
                output=[]
            )
        else:
            state.response.status = ResponseStatus.FAILED

        state.response.error = ErrorInfo(
            type="server_error",
            message=legacy_event.get("error", "Unknown error")
        )

        events.append(ResponseFailedEvent(response=state.response))

    return events


def parse_harness_progress_event(
    *,
    node_name: str | None,
    message: str | None,
    report_id: str | None = None,
) -> Optional[NeosHarnessEvent]:
    if node_name not in {"research_harness", "research_harness_repair"}:
        return None
    if not message:
        return None
    try:
        payload = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("event"):
        return None
    return NeosHarnessEvent(
        event=str(payload.get("event")),
        run_id=payload.get("run_id"),
        report_id=report_id,
        timestamp=payload.get("timestamp"),
        data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
    )


def graph_subagent_event_from(data: Dict[str, Any]) -> NeosGraphSubagentEvent:
    """`graph_subagent_step`/`_folded` 페이로드 → `neos:graph_subagent`.

    **허용 목록으로** 옮긴다. 페이로드를 통째로 펼치면 나중에 누군가 폴드
    페이로드에 요약 본문을 더했을 때 그것이 그대로 화면에 샌다 -- 본문은
    unverified 검색 결과로만 가야 한다(`subagent_nodes.py`).
    """
    folded = data.get("kind") == "graph_subagent_folded"
    max_steps = data.get("max_advances")
    return NeosGraphSubagentEvent(
        node=str(data.get("node") or ""),
        label=data.get("label"),
        phase="folded" if folded else "step",
        status=str(data.get("status") or "unknown") if folded else "running",
        run_id=data.get("run_id"),
        steps=int(data.get("steps") or 0),
        max_steps=int(max_steps) if isinstance(max_steps, int) else None,
        exit_reason=data.get("exit_reason") if folded else None,
        error_code=data.get("error_code") if folded else None,
    )


def format_sse_event(event: OpenResponsesEvent) -> str:
    """
    Format an OpenResponses event as an SSE string

    Args:
        event: The OpenResponses event to format

    Returns:
        SSE formatted string with event type and data lines
    """
    event_dict = event.model_dump()
    event_type = event_dict.get("type", "")

    # SSE format: event line + data line
    return f"event: {event_type}\ndata: {json.dumps(event_dict)}\n\n"


def format_done_token() -> str:
    """Return the SSE [DONE] token"""
    return "data: [DONE]\n\n"


class OpenResponsesStreamAdapter:
    """
    Adapter class for converting legacy streams to OpenResponses format

    Usage:
        adapter = OpenResponsesStreamAdapter()

        for legacy_chunk in legacy_stream:
            for event in adapter.process(legacy_chunk):
                yield format_sse_event(event)

        yield format_done_token()
    """

    def __init__(self):
        self.state = StreamAdapterState()

    def process(self, legacy_event: Dict[str, Any]) -> Generator[OpenResponsesEvent, None, None]:
        """
        Process a legacy event and yield OpenResponses events

        Args:
            legacy_event: Legacy event dict

        Yields:
            OpenResponses events
        """
        events = adapt_legacy_event(legacy_event, self.state)
        for event in events:
            yield event

    def reset(self):
        """Reset adapter state for a new stream"""
        self.state.reset()


# ============================================================================
# Convenience Functions
# ============================================================================

def create_stream_generator(
    response_id: str,
    message_id: str,
) -> tuple[StreamAdapterState, OpenResponsesEvent]:
    """
    Create initial state and event for a new stream

    Returns:
        Tuple of (state, initial event)
    """
    state = StreamAdapterState()
    state.response = create_response(response_id, message_id)
    state.message_item = state.response.output[0] if state.response.output else None
    state.started = True

    return state, ResponseInProgressEvent(response=state.response)


def create_text_delta_event(
    state: StreamAdapterState,
    delta: str
) -> OutputTextDeltaEvent:
    """Create a text delta event"""
    if state.message_item:
        state.message_item.add_text(delta)

    return OutputTextDeltaEvent(
        item_id=state.message_item.id if state.message_item else "",
        output_index=0,
        content_index=0,
        delta=delta
    )


def create_function_call_event(
    state: StreamAdapterState,
    node_name: str,
    agent_name: str
) -> OutputItemAddedEvent:
    """Create a function call added event"""
    fc_id = f"fc_{node_name}_{int(time.time() * 1000)}"
    function_call = FunctionCallItem(
        id=fc_id,
        call_id=node_name,
        name=agent_name,
        arguments="{}",
        status=ItemStatus.IN_PROGRESS
    )

    state.function_calls[node_name] = function_call
    state.output_index += 1

    return OutputItemAddedEvent(
        output_index=state.output_index,
        item=function_call
    )


def create_completed_event(
    state: StreamAdapterState,
    usage: Optional[Dict[str, int]] = None
) -> ResponseCompletedEvent:
    """Create a response completed event"""
    if state.response:
        state.response.status = ResponseStatus.COMPLETED

        if state.message_item:
            state.message_item.status = ItemStatus.COMPLETED

        if usage:
            state.response.usage = UsageInfo(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0)
            )

        # Add function calls to output
        for fc in state.function_calls.values():
            if fc not in state.response.output:
                state.response.output.append(fc)

    return ResponseCompletedEvent(response=state.response)


def create_reasoning_start_events(
    state: StreamAdapterState,
) -> List[OpenResponsesEvent]:
    """
    Create events for starting a reasoning item (thinking block)

    Returns:
        List of [OutputItemAddedEvent] for the new reasoning item
    """
    reasoning_id = f"reasoning_{int(time.time() * 1000)}"
    state.reasoning_item = ReasoningItem(
        id=reasoning_id,
        status=ItemStatus.IN_PROGRESS,
    )
    state.reasoning_content = ""
    state.output_index += 1

    # Add reasoning item to response output
    if state.response:
        state.response.output.append(state.reasoning_item)

    return [
        OutputItemAddedEvent(
            output_index=state.output_index,
            item=state.reasoning_item,
        )
    ]


def create_reasoning_delta_event(
    state: StreamAdapterState,
    delta: str,
) -> ReasoningContentDeltaEvent:
    """Create a reasoning content delta event"""
    state.reasoning_content += delta

    # Update reasoning item content
    if state.reasoning_item:
        state.reasoning_item.content = state.reasoning_content

    return ReasoningContentDeltaEvent(
        item_id=state.reasoning_item.id if state.reasoning_item else "",
        output_index=state.output_index,
        delta=delta,
    )


def create_reasoning_done_events(
    state: StreamAdapterState,
) -> List[OpenResponsesEvent]:
    """
    Create events for completing a reasoning item

    Returns:
        List of [ReasoningContentDoneEvent, OutputItemDoneEvent]
    """
    events: List[OpenResponsesEvent] = []

    if state.reasoning_item:
        state.reasoning_item.status = ItemStatus.COMPLETED
        state.reasoning_item.content = state.reasoning_content

        events.append(ReasoningContentDoneEvent(
            item_id=state.reasoning_item.id,
            output_index=state.output_index,
            text=state.reasoning_content,
        ))
        events.append(OutputItemDoneEvent(
            output_index=state.output_index,
            item=state.reasoning_item,
        ))

    return events
