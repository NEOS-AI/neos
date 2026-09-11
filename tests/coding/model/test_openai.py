from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

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
from neos.coding.model.errors import CodingModelError
from neos.coding.model.openai import OpenAICodingModel, _to_openai_request


def event(*, content=None, tool_calls=None, finish_reason=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def tool_delta(index: int, *, call_id: str = "", name: str = "", arguments: str = ""):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeStream:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self._events:
            yield item


class FakeCompletions:
    def __init__(self, events: list[object]) -> None:
        self._events = events
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object) -> FakeStream:
        self.requests.append(request)
        return FakeStream(self._events)


class FakeOpenAIClient:
    def __init__(self, events: list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(events))

    @property
    def requests(self) -> list[dict[str, object]]:
        return self.chat.completions.requests


def request(*, model: str = "gpt-5.6-sol") -> ModelRequest:
    return ModelRequest(
        system="Work safely.",
        messages=(
            CanonicalMessage(role="user", content=(TextContent("Read README"),)),
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
        model=model,
        limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
        task_id="ct_1",
        run_id="cr_1",
        turn_id="turn_1",
    )


@pytest.mark.asyncio
async def test_fragmented_tool_json_becomes_one_completed_call() -> None:
    client = FakeOpenAIClient(
        [
            event(tool_calls=[tool_delta(0, call_id="call_1", name="read_file.v1", arguments='{"path":')]),
            event(tool_calls=[tool_delta(0, arguments='"README.md"}')]),
            event(
                finish_reason="tool_calls",
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7),
            ),
        ]
    )

    events = [item async for item in OpenAICodingModel(client).stream(request())]

    assert events[0:2] == [
        ToolInputDelta("call_1", "read_file.v1", '{"path":'),
        ToolInputDelta("call_1", "read_file.v1", '"README.md"}'),
    ]
    assert events[-2] == ToolCallCompleted(
        tool_call_id="call_1",
        name="read_file.v1",
        input={"path": "README.md"},
    )
    assert events[-1] == ModelCompleted(
        stop_reason="tool_use",
        usage=events[-1].usage,
    )
    assert events[-1].usage.input_tokens == 12
    assert events[-1].usage.output_tokens == 7


@pytest.mark.asyncio
async def test_text_and_stop_are_normalized() -> None:
    client = FakeOpenAIClient(
        [
            event(content="hello"),
            event(
                finish_reason="stop",
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            ),
        ]
    )

    events = [item async for item in OpenAICodingModel(client).stream(request())]

    assert events[0] == TextDelta("hello")
    assert events[-1].stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_missing_usage_is_omitted_not_invented_as_zero() -> None:
    client = FakeOpenAIClient([event(content="hello"), event(finish_reason="stop")])

    events = [item async for item in OpenAICodingModel(client).stream(request())]

    assert events[-1].usage is None


def test_gpt6_astra_uses_max_completion_tokens() -> None:
    payload = _to_openai_request(request(model="gpt-6-astra"))

    assert payload["model"] == "gpt-6-astra"
    assert payload["max_completion_tokens"] == 100
    assert "max_tokens" not in payload


def test_legacy_openai_model_keeps_max_tokens() -> None:
    payload = _to_openai_request(request(model="gpt-4o"))

    assert payload["max_tokens"] == 100
    assert "max_completion_tokens" not in payload


@pytest.mark.asyncio
async def test_context_length_error_maps_to_prompt_too_long() -> None:
    http_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(400, request=http_request)

    class RaisingCompletions:
        async def create(self, **request: object):
            raise openai.APIStatusError(
                "context_length_exceeded",
                response=response,
                body={"error": {"code": "context_length_exceeded"}},
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=RaisingCompletions()))

    with pytest.raises(CodingModelError, match="prompt_too_long") as caught:
        _ = [item async for item in OpenAICodingModel(client).stream(request())]

    assert caught.value.retryable is True
