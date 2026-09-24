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
    #: 모델 사고량 (Anthropic `output_config.effort`). 빈 문자열 = 보내지 않는다.
    #:
    #: **여기서 검증하지 않는다.** "이 모델이 이 레벨을 받는가" 는
    #: `neos.config.model_routing.resolve_effort` 가 이미 물었고, 같은 판단을
    #: 두 곳에서 하면 한쪽만 고쳐지는 날이 온다. 이 필드는 그 판단의 **결과**를
    #: 나른다.
    effort: str = ""

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
    # `output_tokens` 의 **내역**이지 별도 합계가 아니다. Anthropic 은 thinking 을
    # 출력으로 청구하고 `output_tokens` 에 이미 넣는다(실측: 54 중 thinking 13).
    # 더하면 두 번 센다.
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


@dataclass(frozen=True, slots=True)
class ThinkingContent:
    """A provider thinking block, replayed byte-for-byte.

    Claude Fable 5.1 binds the signature to the conversation prefix that
    produced it. Never edit one; strip them all at a boundary instead.
    Text may be empty (the default ``display: "omitted"``).
    """

    thinking: str
    signature: str

    def __post_init__(self) -> None:
        if not self.signature:
            raise ValueError("thinking content requires a signature")


@dataclass(frozen=True, slots=True)
class SystemNoteContent:
    """An operator note appended mid-conversation instead of editing system."""

    text: str
    clear_at: Literal["never", "next_user_message"] = "next_user_message"

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("system note text cannot be empty")
        if self.clear_at not in {"never", "next_user_message"}:
            raise ValueError("invalid system note clear_at")


@dataclass(frozen=True, slots=True)
class ToolAdditionContent:
    """Announces that a declared-but-deferred tool is now offered.

    The reveal travels as an appended message instead of a rewritten tool
    array, which is what keeps earlier thinking blocks valid (roadmap K2b).
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool addition requires a tool name")


CanonicalContent: TypeAlias = (
    TextContent
    | ToolUseContent
    | ToolResultContent
    | ThinkingContent
    | SystemNoteContent
    | ToolAdditionContent
)


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    role: Literal["user", "assistant", "tool", "system"]
    content: tuple[CanonicalContent, ...]

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant", "tool", "system"}:
            raise ValueError("invalid canonical message role")
        if not self.content:
            raise ValueError("completed transcript messages require content")
        # A system message is either one note, or one or more tool reveals.
        # Never both: a note is turn-scoped and may be cleared, while a
        # reveal must persist for the rest of the conversation.
        if self.role == "system":
            one_note = len(self.content) == 1 and isinstance(
                self.content[0], SystemNoteContent
            )
            all_additions = all(
                isinstance(item, ToolAdditionContent) for item in self.content
            )
            if not (one_note or all_additions):
                raise ValueError(
                    "system messages hold one note or only tool additions"
                )
        if self.role != "system" and any(
            isinstance(item, (SystemNoteContent, ToolAdditionContent))
            for item in self.content
        ):
            raise ValueError("system notes require the system role")
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
    # Declared but not offered until a tool_addition announces it (roadmap
    # K2b). This is a static property of the tool: if it flipped when the
    # tool was revealed, the tool array would change again and every
    # replayed thinking block would be invalidated -- the exact bug this
    # flag exists to remove. `_request_fingerprint` ignores it for the same
    # reason: it is not part of what the model is offered.
    deferred: bool = False

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
    # Set only on a refusal: the policy category the vendor named.
    stop_category: str = ""

    def __post_init__(self) -> None:
        if not self.stop_reason:
            raise ValueError("model stop reason is required")
        if self.stop_category and self.stop_reason != "refusal":
            raise ValueError("stop category belongs to a refusal")


@dataclass(frozen=True, slots=True)
class ThinkingCompleted:
    thinking: str
    signature: str

    def __post_init__(self) -> None:
        if not self.signature:
            raise ValueError("thinking block requires a signature")


ModelEvent: TypeAlias = (
    TextDelta
    | ToolInputDelta
    | ToolCallCompleted
    | ThinkingCompleted
    | ModelCompleted
)


def strip_thinking(
    messages: tuple[CanonicalMessage, ...],
) -> tuple[CanonicalMessage, ...]:
    """Drop every thinking block; text and tool calls stay.

    The one-time recovery Anthropic documents for a changed prefix. Removing
    only some blocks from the middle is what invalidates later ones.
    """
    stripped: list[CanonicalMessage] = []
    for message in messages:
        kept = tuple(
            item for item in message.content if not isinstance(item, ThinkingContent)
        )
        if len(kept) == len(message.content):
            stripped.append(message)
        elif kept:
            stripped.append(CanonicalMessage(message.role, kept))
    return tuple(stripped)


class CodingModel(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...


def _validate_tool_identity(tool_call_id: str, name: str) -> None:
    if not tool_call_id or not name:
        raise ValueError("tool call id and name are required")


def _validate_tool_input(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("tool input must be an object")
