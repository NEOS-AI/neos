"""Thinking blocks survive the canonical transcript unchanged (roadmap K1)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neos.coding.loop._durable.support import (
    _message_from_mapping,
    _message_to_mapping,
)
from neos.coding.model.anthropic import AnthropicCodingModel, _to_anthropic_request
from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    TextContent,
    ThinkingCompleted,
    ThinkingContent,
    ToolCallCompleted,
    ToolUseContent,
    strip_thinking,
)
from neos.coding.model.openai import _to_openai_request
from tests.coding.model.test_anthropic import (
    FakeAnthropicClient,
    content_start,
    event,
    input_delta,
)

USER = CanonicalMessage("user", (TextContent("Read a.txt"),))
ASSISTANT = CanonicalMessage(
    "assistant",
    (
        ThinkingContent("", "sig-1"),
        ToolUseContent("toolu_1", "read_file.v1", {"path": "a.txt"}),
    ),
)


def _request(messages, *, model: str = "claude-test") -> ModelRequest:
    return ModelRequest(
        system="Work safely.",
        messages=tuple(messages),
        tools=(),
        model=model,
        limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
        task_id="ct_1",
        run_id="cr_1",
        turn_id="turn_1",
    )


def _thinking_start(index: int) -> SimpleNamespace:
    return event(
        "content_block_start",
        index=index,
        content_block=SimpleNamespace(type="thinking", thinking="", signature=""),
    )


def _thinking_delta(index: int, text: str) -> SimpleNamespace:
    return event(
        "content_block_delta",
        index=index,
        delta=SimpleNamespace(type="thinking_delta", thinking=text),
    )


def _signature_delta(index: int, signature: str) -> SimpleNamespace:
    return event(
        "content_block_delta",
        index=index,
        delta=SimpleNamespace(type="signature_delta", signature=signature),
    )


def _tool_use_stop() -> SimpleNamespace:
    return event(
        "message_delta",
        delta=SimpleNamespace(stop_reason="tool_use"),
        usage=SimpleNamespace(output_tokens=3),
    )


@pytest.mark.asyncio
async def test_stream_emits_thinking_with_signature_before_the_tool_call() -> None:
    client = FakeAnthropicClient(
        [
            _thinking_start(0),
            _thinking_delta(0, "Plan: "),
            _thinking_delta(0, "read a.txt"),
            _signature_delta(0, "sig-abc"),
            event("content_block_stop", index=0),
            content_start(1, "toolu_1", "read_file.v1"),
            input_delta(1, '{"path":"a.txt"}'),
            event("content_block_stop", index=1),
            _tool_use_stop(),
        ]
    )

    events = [
        item async for item in AnthropicCodingModel(client).stream(_request((USER,)))
    ]

    thinking = [item for item in events if isinstance(item, ThinkingCompleted)]
    assert thinking == [ThinkingCompleted("Plan: read a.txt", "sig-abc")]
    tool_index = next(
        index for index, item in enumerate(events) if isinstance(item, ToolCallCompleted)
    )
    assert events.index(thinking[0]) < tool_index


@pytest.mark.asyncio
async def test_unsigned_thinking_block_is_not_emitted() -> None:
    client = FakeAnthropicClient(
        [
            _thinking_start(0),
            _thinking_delta(0, "no signature arrives"),
            event("content_block_stop", index=0),
            _tool_use_stop(),
        ]
    )

    events = [
        item async for item in AnthropicCodingModel(client).stream(_request((USER,)))
    ]

    assert not any(isinstance(item, ThinkingCompleted) for item in events)


def test_thinking_content_requires_a_signature() -> None:
    with pytest.raises(ValueError):
        ThinkingContent("reasoning", "")


def test_thinking_is_sent_back_to_anthropic_unchanged() -> None:
    payload = _to_anthropic_request(_request((USER, ASSISTANT)))

    assert payload["messages"][1]["content"][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig-1",
    }


def test_openai_request_carries_no_thinking() -> None:
    payload = _to_openai_request(_request((USER, ASSISTANT), model="gpt-6-sol"))

    assert "sig-1" not in json.dumps(payload)


def test_transcript_mapping_round_trips_thinking() -> None:
    assert _message_from_mapping(_message_to_mapping(ASSISTANT)) == ASSISTANT


def test_strip_thinking_keeps_text_and_tool_calls() -> None:
    stripped = strip_thinking((USER, ASSISTANT))

    assert stripped == (
        USER,
        CanonicalMessage(
            "assistant",
            (ToolUseContent("toolu_1", "read_file.v1", {"path": "a.txt"}),),
        ),
    )
