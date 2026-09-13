from dataclasses import FrozenInstanceError

import pytest

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    ModelUsage,
    TextContent,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)


def model_request(*, messages: tuple[CanonicalMessage, ...]) -> ModelRequest:
    return ModelRequest(
        system="Work safely.",
        messages=messages,
        tools=(
            ToolDefinition(
                name="read_file.v1",
                description="Read a workspace file.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
        ),
        model="claude-test",
        limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
        task_id="ct_1",
        run_id="cr_1",
        turn_id="turn_1",
    )


def test_model_request_accepts_completed_canonical_transcript() -> None:
    request = model_request(
        messages=(
            CanonicalMessage(role="user", content=(TextContent("Inspect it"),)),
            CanonicalMessage(
                role="assistant",
                content=(
                    TextContent("I will inspect it."),
                    ToolUseContent(
                        tool_call_id="tool_1",
                        name="read_file.v1",
                        input={"path": "README.md"},
                    ),
                ),
            ),
            CanonicalMessage(
                role="tool",
                content=(
                    ToolResultContent(
                        tool_call_id="tool_1",
                        status="ok",
                        content={"preview": "hello"},
                    ),
                ),
            ),
        )
    )

    assert request.messages[-1].role == "tool"
    assert request.tools[0].name == "read_file.v1"


def test_model_request_rejects_incomplete_transcript_messages() -> None:
    with pytest.raises(ValueError, match="completed transcript"):
        model_request(messages=(CanonicalMessage(role="assistant", content=()),))


def test_canonical_message_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="canonical message role"):
        CanonicalMessage(role="system", content=(TextContent("no"),))


def test_tool_call_requires_object_input() -> None:
    with pytest.raises(ValueError, match="tool input must be an object"):
        ToolCallCompleted(
            tool_call_id="tool_1",
            name="read_file.v1",
            input=[],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("max_output_tokens", "timeout_sec"),
    [(0, 1), (1, 0), (-1, 1), (1, -1)],
)
def test_model_limits_must_be_positive(
    max_output_tokens: int, timeout_sec: float
) -> None:
    with pytest.raises(ValueError, match="model limits must be positive"):
        ModelLimits(
            max_output_tokens=max_output_tokens,
            timeout_sec=timeout_sec,
        )


def test_model_limits_usable_tokens_follow_catalog_formula() -> None:
    limits = ModelLimits(
        max_output_tokens=8_192,
        timeout_sec=5,
        context_window=200_000,
        thinking_budget=0,
    )
    assert limits.usable_tokens() == 200_000 - 8_192 - 20_000


def test_model_limits_unknown_window_has_no_usable() -> None:
    assert ModelLimits(max_output_tokens=100, timeout_sec=5).usable_tokens() is None


def test_model_limits_reject_negative_thinking_budget() -> None:
    with pytest.raises(ValueError, match="model limits must be positive"):
        ModelLimits(max_output_tokens=100, timeout_sec=5, thinking_budget=-1)


def test_canonical_values_are_immutable() -> None:
    event = TextDelta("hello")

    with pytest.raises(FrozenInstanceError):
        event.text = "changed"  # type: ignore[misc]


def test_all_canonical_event_shapes_are_constructible() -> None:
    events = (
        TextDelta("hello"),
        ToolInputDelta("tool_1", "read_file.v1", '{"path":'),
        ToolCallCompleted("tool_1", "read_file.v1", {"path": "README.md"}),
        ModelCompleted(
            stop_reason="tool_use",
            usage=ModelUsage(input_tokens=10, output_tokens=4),
        ),
    )

    assert [type(event).__name__ for event in events] == [
        "TextDelta",
        "ToolInputDelta",
        "ToolCallCompleted",
        "ModelCompleted",
    ]


def test_tool_definition_requires_object_json_schema() -> None:
    with pytest.raises(ValueError, match="object JSON schema"):
        ToolDefinition(
            name="bad.v1",
            description="bad",
            input_schema={"type": "array"},
        )
