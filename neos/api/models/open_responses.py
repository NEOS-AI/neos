"""
OpenResponses Specification Models

This module defines Pydantic models for OpenResponses specification compliance.
See: https://www.openresponses.org/specification

The OpenResponses specification provides a standard format for LLM API responses,
enabling interoperability between different AI providers.
"""

from typing import Optional, List, Dict, Any, Literal, Union
from pydantic import BaseModel, Field
from enum import Enum
import time


# ============================================================================
# Enums and Constants
# ============================================================================

class ItemStatus(str, Enum):
    """Status values for output items"""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ResponseStatus(str, Enum):
    """Status values for response objects"""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ItemType(str, Enum):
    """Standard output item types"""
    MESSAGE = "message"
    FUNCTION_CALL = "function_call"
    REASONING = "reasoning"


# ============================================================================
# Content Parts
# ============================================================================

class OutputTextPart(BaseModel):
    """Output text content part"""
    type: Literal["output_text"] = "output_text"
    text: str = ""


class InputTextPart(BaseModel):
    """Input text content part"""
    type: Literal["input_text"] = "input_text"
    text: str


class InputFilePart(BaseModel):
    """Input file content part"""
    type: Literal["input_file"] = "input_file"
    file: Dict[str, Any]  # { url, media_type, name }


# ============================================================================
# Output Items
# ============================================================================

class MessageItem(BaseModel):
    """Message output item (assistant response)"""
    type: Literal["message"] = "message"
    id: str
    role: Literal["assistant"] = "assistant"
    status: ItemStatus = ItemStatus.IN_PROGRESS
    content: List[OutputTextPart] = Field(default_factory=list)

    def add_text(self, text: str) -> None:
        """Add text to the first content part or create one"""
        if not self.content:
            self.content.append(OutputTextPart())
        self.content[0].text += text


class FunctionCallItem(BaseModel):
    """Function call output item (tool invocation)"""
    type: Literal["function_call"] = "function_call"
    id: str
    call_id: str
    name: str
    arguments: str = "{}"
    status: ItemStatus = ItemStatus.IN_PROGRESS


class ReasoningItem(BaseModel):
    """Reasoning output item (chain of thought)"""
    type: Literal["reasoning"] = "reasoning"
    id: str
    status: ItemStatus = ItemStatus.IN_PROGRESS
    content: Optional[str] = None
    encrypted_content: Optional[str] = None
    summary: Optional[str] = None


OutputItem = Union[MessageItem, FunctionCallItem, ReasoningItem]


# ============================================================================
# Response Object
# ============================================================================

class UsageInfo(BaseModel):
    """Token usage information"""
    input_tokens: int = 0
    output_tokens: int = 0


class ErrorInfo(BaseModel):
    """Error information in OpenResponses format"""
    type: str  # "invalid_request", "not_found", "too_many_requests", "server_error"
    message: str
    param: Optional[str] = None
    code: Optional[str] = None


class ResponseObject(BaseModel):
    """
    OpenResponses Response object

    Contains the full response state including all output items,
    usage information, and status.
    """
    id: str
    object: Literal["response"] = "response"
    created_at: int = Field(default_factory=lambda: int(time.time()))
    status: ResponseStatus = ResponseStatus.IN_PROGRESS
    output: List[OutputItem] = Field(default_factory=list)
    usage: Optional[UsageInfo] = None
    error: Optional[ErrorInfo] = None


# ============================================================================
# Streaming Events (Standard)
# ============================================================================

class ResponseInProgressEvent(BaseModel):
    """Event: response.in_progress - Response has started"""
    type: Literal["response.in_progress"] = "response.in_progress"
    response: ResponseObject


class ResponseCompletedEvent(BaseModel):
    """Event: response.completed - Response is complete"""
    type: Literal["response.completed"] = "response.completed"
    response: ResponseObject


class ResponseFailedEvent(BaseModel):
    """Event: response.failed - Response has failed"""
    type: Literal["response.failed"] = "response.failed"
    response: ResponseObject


class OutputItemAddedEvent(BaseModel):
    """Event: response.output_item.added - New output item added"""
    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: int
    item: OutputItem


class OutputItemDoneEvent(BaseModel):
    """Event: response.output_item.done - Output item completed"""
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int
    item: OutputItem


class OutputTextDeltaEvent(BaseModel):
    """Event: response.output_text.delta - Text content delta"""
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    item_id: str
    output_index: int
    content_index: int
    delta: str


class OutputTextDoneEvent(BaseModel):
    """Event: response.output_text.done - Text content completed"""
    type: Literal["response.output_text.done"] = "response.output_text.done"
    item_id: str
    output_index: int
    content_index: int
    text: str


class ContentPartAddedEvent(BaseModel):
    """Event: response.content_part.added - Content part added"""
    type: Literal["response.content_part.added"] = "response.content_part.added"
    item_id: str
    output_index: int
    content_index: int
    part: OutputTextPart


class ContentPartDoneEvent(BaseModel):
    """Event: response.content_part.done - Content part completed"""
    type: Literal["response.content_part.done"] = "response.content_part.done"
    item_id: str
    output_index: int
    content_index: int
    part: OutputTextPart


class ReasoningContentDeltaEvent(BaseModel):
    """Event: response.reasoning.delta - Reasoning content delta (thinking block)"""
    type: Literal["response.reasoning.delta"] = "response.reasoning.delta"
    item_id: str
    output_index: int
    delta: str


class ReasoningContentDoneEvent(BaseModel):
    """Event: response.reasoning.done - Reasoning content completed"""
    type: Literal["response.reasoning.done"] = "response.reasoning.done"
    item_id: str
    output_index: int
    text: str


class ReasoningSummaryDeltaEvent(BaseModel):
    """Event: response.reasoning_summary.delta - Reasoning summary delta"""
    type: Literal["response.reasoning_summary.delta"] = "response.reasoning_summary.delta"
    item_id: str
    output_index: int
    delta: str


class ReasoningSummaryDoneEvent(BaseModel):
    """Event: response.reasoning_summary.done - Reasoning summary completed"""
    type: Literal["response.reasoning_summary.done"] = "response.reasoning_summary.done"
    item_id: str
    output_index: int
    text: str


# ============================================================================
# Streaming Events (Neos Extensions)
# ============================================================================

class NeosArtifactMetaEvent(BaseModel):
    """
    Event: neos:artifact_meta - Artifact metadata

    Neos extension event for artifact creation.
    Uses provider prefix as per OpenResponses spec.
    """
    type: Literal["neos:artifact_meta"] = "neos:artifact_meta"
    artifact_id: str
    artifact_title: str
    artifact_kind: str  # "text", "code", "sheet", "image"


class NeosArtifactDeltaEvent(BaseModel):
    """
    Event: neos:artifact_delta - Artifact content delta

    Neos extension event for artifact content streaming.
    """
    type: Literal["neos:artifact_delta"] = "neos:artifact_delta"
    content: str


class NeosArtifactFinishEvent(BaseModel):
    """
    Event: neos:artifact_finish - Artifact completion

    Neos extension event for artifact completion.
    """
    type: Literal["neos:artifact_finish"] = "neos:artifact_finish"
    artifact_id: Optional[str] = None


class NeosWorkflowProgressEvent(BaseModel):
    """
    Event: neos:workflow_progress - Workflow progress update

    Neos extension event for workflow progress tracking.
    """
    type: Literal["neos:workflow_progress"] = "neos:workflow_progress"
    progress_percent: int
    message: Optional[str] = None


class NeosUIFrameEvent(BaseModel):
    """
    Event: neos:ui_frame — Phase 8 (A2UI) UIFrame 컴포넌트 페이로드

    Neos 확장 이벤트. UIFrameGenerator가 생성한 컴포넌트 목록을
    클라이언트에 전달하기 위해 사용.
    """
    type: Literal["neos:ui_frame"] = "neos:ui_frame"
    ui_frame: Dict[str, Any]


# ============================================================================
# Union Types
# ============================================================================

StandardStreamEvent = Union[
    ResponseInProgressEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    OutputItemAddedEvent,
    OutputItemDoneEvent,
    OutputTextDeltaEvent,
    OutputTextDoneEvent,
    ContentPartAddedEvent,
    ContentPartDoneEvent,
    ReasoningContentDeltaEvent,
    ReasoningContentDoneEvent,
    ReasoningSummaryDeltaEvent,
    ReasoningSummaryDoneEvent,
]

NeosExtensionEvent = Union[
    NeosArtifactMetaEvent,
    NeosArtifactDeltaEvent,
    NeosArtifactFinishEvent,
    NeosWorkflowProgressEvent,
    NeosUIFrameEvent,          # Phase 8 (A2UI)
]

OpenResponsesEvent = Union[StandardStreamEvent, NeosExtensionEvent]


# ============================================================================
# Error Response
# ============================================================================

class OpenResponsesErrorResponse(BaseModel):
    """
    OpenResponses-compliant error response

    All errors are wrapped in an "error" object with standardized fields.
    """
    error: ErrorInfo


# ============================================================================
# Helper Functions
# ============================================================================

def create_response(response_id: str, message_id: str) -> ResponseObject:
    """
    Create a new response object with an initial message item

    Args:
        response_id: Unique ID for the response
        message_id: Unique ID for the initial message item

    Returns:
        ResponseObject with in_progress status
    """
    message_item = MessageItem(
        id=message_id,
        status=ItemStatus.IN_PROGRESS,
        content=[OutputTextPart()]
    )

    return ResponseObject(
        id=response_id,
        status=ResponseStatus.IN_PROGRESS,
        output=[message_item]
    )


def map_error_type(legacy_type: str) -> str:
    """
    Map legacy error types to OpenResponses error types

    Args:
        legacy_type: Legacy error type (e.g., "bad_request", "unauthorized")

    Returns:
        OpenResponses error type
    """
    mapping = {
        "bad_request": "invalid_request",
        "unauthorized": "invalid_request",
        "forbidden": "invalid_request",
        "not_found": "not_found",
        "rate_limit": "too_many_requests",
        "offline": "server_error",
    }
    return mapping.get(legacy_type, "server_error")
