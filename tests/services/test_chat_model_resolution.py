from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.api.models.chat_models import CreateConversationRequest
from neos.api.services.chat_service import resolve_new_chat_model
from neos.services import chat_llm_service
from neos.services.chat_llm_service import (
    ChatLLMService,
    resolve_conversation_chat_model,
)


def test_new_chat_without_selection_uses_anthropic_everyday() -> None:
    request = CreateConversationRequest()

    assert request.model_name is None
    assert resolve_new_chat_model(request.model_name) == "claude-sonnet-5"


def test_explicit_chat_model_is_not_replaced() -> None:
    assert resolve_new_chat_model("openai/gpt-4.1") == "openai/gpt-4.1"


def test_stored_conversation_model_is_not_replaced() -> None:
    assert resolve_conversation_chat_model("openai/gpt-4.1") == "openai/gpt-4.1"


class _RecordingAnthropicStream:
    def __init__(self) -> None:
        self.final_message = SimpleNamespace(
            content=[],
            usage=SimpleNamespace(input_tokens=2, output_tokens=3),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def get_final_message(self):
        return self.final_message


class _RecordingAnthropicClient:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls
        self.messages = self

    def stream(self, **kwargs):
        self._calls.append(kwargs)
        return _RecordingAnthropicStream()


class _RecordingGenericLLM:
    def __init__(self, messages: list[list]) -> None:
        self._messages = messages

    async def astream(self, messages):
        self._messages.append(messages)
        if False:
            yield None


def _tool_stream(
    service: ChatLLMService,
    path: str,
    *,
    model_name: str | None,
):
    common = {
        "conversation_id": "conversation-1",
        "message_id": "message-1",
        "conversation_messages": [{"role": "user", "content": "hello"}],
        "model_name": model_name,
        "system_prompt": "system",
        "temperature": 0.7,
        "max_tokens": 321,
    }
    if path == "tools":
        return service.generate_response_stream_with_tools(
            **common,
            tools=[
                {
                    "name": "render",
                    "description": "Render an artifact",
                    "input_schema": {"type": "object"},
                }
            ],
        )
    return service.generate_response_stream_with_tool_search(
        **common,
        core_tools=[],
        search_handler=SimpleNamespace(),
        max_tool_rounds=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["tools", "tool_search"])
async def test_claude_5_tool_streams_normalize_direct_sdk_kwargs(
    monkeypatch,
    path: str,
) -> None:
    sdk_calls: list[dict] = []
    monkeypatch.setattr(
        chat_llm_service.anthropic,
        "AsyncAnthropic",
        lambda **_: _RecordingAnthropicClient(sdk_calls),
    )
    monkeypatch.setattr(
        chat_llm_service.cost_calculator,
        "calculate_cost",
        AsyncMock(return_value={"total_cost": 0.0}),
    )

    events = [
        event
        async for event in _tool_stream(
            ChatLLMService(),
            path,
            model_name=None,
        )
    ]

    assert len(sdk_calls) == 1
    assert sdk_calls[0]["model"] == "claude-sonnet-5"
    assert sdk_calls[0]["thinking"] == {"type": "adaptive"}
    assert "temperature" not in sdk_calls[0]
    assert events[0] == {
        "type": "start",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["tools", "tool_search"])
async def test_explicit_openai_tool_streams_use_openai_provider_boundary(
    monkeypatch,
    path: str,
) -> None:
    factory_calls: list[dict] = []
    streamed_messages: list[list] = []

    def fake_create_llm(**kwargs):
        factory_calls.append(kwargs)
        return _RecordingGenericLLM(streamed_messages)

    monkeypatch.setattr(chat_llm_service, "create_llm", fake_create_llm)
    monkeypatch.setattr(
        chat_llm_service.anthropic,
        "AsyncAnthropic",
        lambda **_: pytest.fail("explicit OpenAI selection called Anthropic"),
    )
    monkeypatch.setattr(
        chat_llm_service.context_optimizer,
        "check_and_optimize_context",
        AsyncMock(
            side_effect=lambda messages, **_: (messages, None)
        ),
    )
    monkeypatch.setattr(
        chat_llm_service.cost_calculator,
        "calculate_cost",
        AsyncMock(return_value={"total_cost": 0.0}),
    )

    events = [
        event
        async for event in _tool_stream(
            ChatLLMService(),
            path,
            model_name="gpt-5.6-terra",
        )
    ]

    assert factory_calls == [
        {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "temperature": 0.7,
            "streaming": True,
            "max_tokens": 321,
        }
    ]
    assert len(streamed_messages) == 1
    assert events[0] == {
        "type": "start",
        "model": "gpt-5.6-terra",
        "provider": "openai",
    }
    assert events[-1]["type"] == "complete"
    assert events[-1]["provider"] == "openai"
