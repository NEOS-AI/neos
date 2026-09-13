from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from neos.config.model_identity import usable_window_tokens


@dataclass(frozen=True, slots=True)
class ModelLimits:
    max_output_tokens: int
    timeout_sec: float
    context_window: int | None = None
    input_limit: int | None = None
    thinking_budget: int = 0

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1 or self.timeout_sec <= 0:
            raise ValueError("model limits must be positive")
        if self.context_window is not None and self.context_window <= 0:
            raise ValueError("model limits must be positive")
        if self.input_limit is not None and self.input_limit <= 0:
            raise ValueError("model limits must be positive")
        if self.thinking_budget < 0:
            raise ValueError("model limits must be positive")

    def usable_tokens(self) -> int | None:
        return usable_window_tokens(
            context_window=self.context_window,
            max_output_tokens=self.max_output_tokens,
            input_limit=self.input_limit,
            thinking_budget=self.thinking_budget,
        )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        if (
            self.input_tokens < 0
            or self.output_tokens < 0
            or self.cache_read_tokens < 0
            or self.cache_write_tokens < 0
            or self.reasoning_tokens < 0
        ):
            raise ValueError("model usage cannot be negative")


@dataclass(frozen=True, slots=True)
class TextContent:
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("completed text content cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolUseContent:
    tool_call_id: str
    name: str
    input: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_tool_identity(self.tool_call_id, self.name)
        _validate_tool_input(self.input)


@dataclass(frozen=True, slots=True)
class ToolResultContent:
    tool_call_id: str
    status: Literal["ok", "error", "denied"]
    content: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.tool_call_id:
            raise ValueError("tool result id cannot be empty")
        if not isinstance(self.content, Mapping):
            raise ValueError("tool result content must be an object")


CanonicalContent: TypeAlias = TextContent | ToolUseContent | ToolResultContent


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    role: Literal["user", "assistant", "tool"]
    content: tuple[CanonicalContent, ...]

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant", "tool"}:
            raise ValueError("invalid canonical message role")
        if not self.content:
            raise ValueError("completed transcript messages require content")
        if self.role == "tool" and not all(
            isinstance(item, ToolResultContent) for item in self.content
        ):
            raise ValueError("tool messages require completed tool results")
        if self.role != "tool" and any(
            isinstance(item, ToolResultContent) for item in self.content
        ):
            raise ValueError("tool results require the tool role")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.name or not self.description:
            raise ValueError("tool definition name and description are required")
        if (
            not isinstance(self.input_schema, Mapping)
            or self.input_schema.get("type") != "object"
        ):
            raise ValueError("tool definition requires an object JSON schema")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    system: str
    messages: tuple[CanonicalMessage, ...]
    tools: tuple[ToolDefinition, ...]
    model: str
    limits: ModelLimits
    task_id: str
    run_id: str
    turn_id: str

    def __post_init__(self) -> None:
        if not self.system or not self.model:
            raise ValueError("model system instructions and model are required")
        if not self.task_id or not self.run_id or not self.turn_id:
            raise ValueError("model tracing identifiers are required")
        if any(not message.content for message in self.messages):
            raise ValueError("completed transcript messages require content")
        names = tuple(tool.name for tool in self.tools)
        if len(names) != len(set(names)):
            raise ValueError("tool definition names must be unique")


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolInputDelta:
    tool_call_id: str
    name: str
    partial_json: str

    def __post_init__(self) -> None:
        _validate_tool_identity(self.tool_call_id, self.name)


@dataclass(frozen=True, slots=True)
class ToolCallCompleted:
    tool_call_id: str
    name: str
    input: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_tool_identity(self.tool_call_id, self.name)
        _validate_tool_input(self.input)


@dataclass(frozen=True, slots=True)
class ModelCompleted:
    stop_reason: str
    usage: ModelUsage | None = None

    def __post_init__(self) -> None:
        if not self.stop_reason:
            raise ValueError("model stop reason is required")


ModelEvent: TypeAlias = (
    TextDelta | ToolInputDelta | ToolCallCompleted | ModelCompleted
)


class CodingModel(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...


def _validate_tool_identity(tool_call_id: str, name: str) -> None:
    if not tool_call_id or not name:
        raise ValueError("tool call id and name are required")


def _validate_tool_input(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("tool input must be an object")
