from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.coding.model.anthropic import (
    AnthropicCodingModel,
    CodingModelError,
)
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    TextContent,
    TextDelta,
    ToolCallCompleted,
    ToolDefinition,
    ToolInputDelta,
)


def event(event_type: str, **values: object) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, **values)


def content_start(index: int, tool_id: str, name: str) -> SimpleNamespace:
    return event(
        "content_block_start",
        index=index,
        content_block=SimpleNamespace(
            type="tool_use", id=tool_id, name=name, input={}
        ),
    )


def input_delta(index: int, partial_json: str) -> SimpleNamespace:
    return event(
        "content_block_delta",
        index=index,
        delta=SimpleNamespace(
            type="input_json_delta", partial_json=partial_json
        ),
    )


class FakeStream:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self._events:
            yield item


class FakeMessages:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events
        self.requests: list[dict[str, object]] = []

    def stream(self, **request: object) -> FakeStream:
        self.requests.append(request)
        return FakeStream(self._events)


class FakeAnthropicClient:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self.messages = FakeMessages(events)


def request() -> ModelRequest:
    return ModelRequest(
        system="Work safely.",
        messages=(
            CanonicalMessage(
                role="user", content=(TextContent("Read README"),)
            ),
        ),
        tools=(
            ToolDefinition(
                name="read_file.v1",
                description="Read a file",
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


@pytest.mark.asyncio
async def test_fragmented_tool_json_becomes_one_completed_call() -> None:
    client = FakeAnthropicClient(
        [
            event(
                "message_start",
                message=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=12, output_tokens=0)
                ),
            ),
            content_start(0, "toolu_1", "read_file.v1"),
            input_delta(0, '{"path":'),
            input_delta(0, '"README.md"}'),
            event("content_block_stop", index=0),
            event(
                "message_delta",
                delta=SimpleNamespace(stop_reason="tool_use"),
                usage=SimpleNamespace(output_tokens=7),
            ),
        ]
    )

    events = [
        item async for item in AnthropicCodingModel(client).stream(request())
    ]

    assert events[0:2] == [
        ToolInputDelta("toolu_1", "read_file.v1", '{"path":'),
        ToolInputDelta("toolu_1", "read_file.v1", '"README.md"}'),
    ]
    assert events[-2] == ToolCallCompleted(
        tool_call_id="toolu_1",
        name="read_file.v1",
        input={"path": "README.md"},
    )
    assert events[-1] == ModelCompleted(
        stop_reason="tool_use",
        usage=events[-1].usage,
    )
    assert events[-1].usage.input_tokens == 12
    assert events[-1].usage.output_tokens == 7
    assert events[-1].usage.cache_read_tokens == 0
    assert events[-1].usage.cache_write_tokens == 0
    assert client.messages.requests[0]["model"] == "claude-test"


@pytest.mark.asyncio
async def test_usage_extracts_cache_window_tokens() -> None:
    client = FakeAnthropicClient(
        [
            event(
                "message_start",
                message=SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=20,
                        cache_read_input_tokens=8,
                        cache_creation_input_tokens=3,
                    )
                ),
            ),
            event(
                "message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(output_tokens=5, reasoning_tokens=2),
            ),
        ]
    )
    events = [
        item async for item in AnthropicCodingModel(client).stream(request())
    ]
    usage = events[-1].usage
    assert usage.input_tokens == 20
    assert usage.output_tokens == 5
    assert usage.cache_read_tokens == 8
    assert usage.cache_write_tokens == 3
    assert usage.reasoning_tokens == 2


@pytest.mark.asyncio
async def test_thinking_tokens_are_read_where_the_api_puts_them() -> None:
    """실 API 의 `message_delta.usage` 모양 그대로(2026-09-24 실측).

    위 테스트의 `reasoning_tokens` 는 API 에 없는 필드다 -- 그 가짜 하나로
    reasoning 이 실제로는 늘 0 인 것이 가려져 있었다.
    """
    client = FakeAnthropicClient(
        [
            event(
                "message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(
                    output_tokens=54,
                    output_tokens_details=SimpleNamespace(thinking_tokens=13),
                ),
            ),
        ]
    )
    events = [
        item async for item in AnthropicCodingModel(client).stream(request())
    ]
    assert events[-1].usage.reasoning_tokens == 13


@pytest.mark.asyncio
async def test_text_delta_is_normalized() -> None:
    client = FakeAnthropicClient(
        [
            event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="hello"),
            ),
            event(
                "message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(output_tokens=1),
            ),
        ]
    )

    events = [
        item async for item in AnthropicCodingModel(client).stream(request())
    ]

    assert events == [
        TextDelta("hello"),
        ModelCompleted(stop_reason="end_turn", usage=events[-1].usage),
    ]


@pytest.mark.asyncio
async def test_oversized_partial_json_fails_before_accumulating_more() -> None:
    client = FakeAnthropicClient(
        [content_start(0, "toolu_1", "read_file.v1"), input_delta(0, "x" * 9)]
    )
    model = AnthropicCodingModel(client, max_tool_input_bytes=8)

    with pytest.raises(CodingModelError, match="tool_input_too_large") as caught:
        _ = [item async for item in model.stream(request())]

    assert caught.value.code == "tool_input_too_large"
    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("partial_json", ["[]", '{"path":'])
async def test_invalid_completed_tool_json_is_rejected(partial_json: str) -> None:
    client = FakeAnthropicClient(
        [
            content_start(0, "toolu_1", "read_file.v1"),
            input_delta(0, partial_json),
            event("content_block_stop", index=0),
        ]
    )

    with pytest.raises(CodingModelError, match="tool_input_invalid"):
        _ = [item async for item in AnthropicCodingModel(client).stream(request())]


@pytest.mark.asyncio
async def test_tool_json_nesting_is_bounded() -> None:
    client = FakeAnthropicClient(
        [
            content_start(0, "toolu_1", "read_file.v1"),
            input_delta(0, '{"a":{"b":{"c":1}}}'),
            event("content_block_stop", index=0),
        ]
    )

    with pytest.raises(CodingModelError, match="tool_input_too_deep"):
        _ = [
            item
            async for item in AnthropicCodingModel(
                client, max_tool_input_depth=2
            ).stream(request())
        ]
