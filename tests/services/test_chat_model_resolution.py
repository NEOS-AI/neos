from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.api.models.chat_models import (
    CreateConversationRequest,
    CreateTemplateRequest,
)
from neos.api.services import chat_service
from neos.api.services.chat_service import ChatService, resolve_new_chat_model
from neos.api.services.chat_stream_pipeline import resolve_turn_model_name
from neos.config.model_config import model_config
from neos.services import chat_llm_service
import neos.utils.anthropic_client as anthropic_client_module
from neos.services.chat_llm_service import (
    ChatLLMService,
    resolve_conversation_chat_model,
)

pytestmark = pytest.mark.no_db

_EVERYDAY = model_config.catalog.role_aliases["sonnet-5"].current


def test_new_chat_without_selection_uses_anthropic_everyday() -> None:
    request = CreateConversationRequest()

    assert request.model_name is None
    assert resolve_new_chat_model(request.model_name) == _EVERYDAY


def test_explicit_chat_model_is_not_replaced() -> None:
    assert resolve_new_chat_model("gpt-5.6-sol") == "gpt-5.6-sol"


def test_new_chat_user_cookie_is_remapped() -> None:
    assert resolve_new_chat_model("openai/gpt-4.1") == "gpt-5.6-sol"


def test_gemini_pin_is_stored_without_calling_resolve_model(monkeypatch) -> None:
    """Selectable Gemini is not role-routed. resolve_model(provider='gemini') 500s."""

    def _boom(**kwargs):
        raise AssertionError(f"resolve_model must not run for Gemini: {kwargs}")

    monkeypatch.setattr(chat_service, "resolve_model", _boom)
    assert resolve_new_chat_model("gemini-1.5-pro-latest") == "gemini-1.5-pro-latest"


def test_openai_selection_resolves_with_openai_provider(monkeypatch) -> None:
    seen: dict = {}
    real = chat_service.resolve_model

    def _spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(chat_service, "resolve_model", _spy)
    assert resolve_new_chat_model("gpt-5.6-sol") == "gpt-5.6-sol"
    assert seen["provider"] == "openai"
    assert seen["user_model"] == "gpt-5.6-sol"
    assert seen["role"] == "everyday"


def test_anthropic_selection_resolves_with_anthropic_provider(monkeypatch) -> None:
    seen: dict = {}
    real = chat_service.resolve_model

    def _spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(chat_service, "resolve_model", _spy)
    assert resolve_new_chat_model("claude-opus-5") == "claude-opus-5"
    assert seen["provider"] == "anthropic"
    assert seen["user_model"] == "claude-opus-5"


def test_stored_conversation_model_is_not_replaced() -> None:
    assert resolve_conversation_chat_model("openai/gpt-4.1") == "openai/gpt-4.1"


def test_turn_override_canonicalizes_gateway_id_to_pin() -> None:
    assert (
        resolve_turn_model_name(
            {"model": "anthropic/claude-sonnet-5"},
            {"model_name": "gpt-4o-mini"},
        )
        == "claude-sonnet-5"
    )


def test_turn_override_applies_user_remap() -> None:
    assert (
        resolve_turn_model_name(
            {"model": "anthropic/claude-opus-4.5"},
            {"model_name": "gpt-4o-mini"},
        )
        == "claude-opus-5"
    )


def test_turn_override_accepts_selectable_gemini_pin() -> None:
    assert (
        resolve_turn_model_name(
            {"model": "gemini-1.5-pro-latest"},
            {"model_name": "claude-sonnet-5"},
        )
        == "gemini-1.5-pro-latest"
    )


def test_turn_falls_back_to_conversation_without_remapping() -> None:
    assert (
        resolve_turn_model_name(
            {},
            {"model_name": "anthropic/claude-opus-4.5"},
        )
        == "anthropic/claude-opus-4.5"
    )


def test_new_template_without_selection_defers_to_role_routing() -> None:
    request = CreateTemplateRequest(name="Research", created_by="owner")

    assert request.default_model is None


def _capture_template_insert(monkeypatch) -> list[tuple]:
    """Record positional INSERT arguments for conversation_templates."""
    inserted: list[tuple] = []

    async def fake_execute(query, *args):
        inserted.append(args)
        return None

    monkeypatch.setattr(chat_service.db_manager, "execute", fake_execute)
    monkeypatch.setattr(
        ChatService,
        "get_template",
        AsyncMock(return_value={}),
    )
    return inserted


# INSERT column order: template_id, name, description, category, default_model
_DEFAULT_MODEL_ARG = 4


@pytest.mark.asyncio
async def test_template_creation_stores_the_everyday_role_model(monkeypatch) -> None:
    inserted = _capture_template_insert(monkeypatch)

    await ChatService.create_template(name="Research", created_by="owner")

    assert inserted[0][_DEFAULT_MODEL_ARG] == _EVERYDAY


@pytest.mark.asyncio
async def test_explicit_template_model_is_not_replaced(monkeypatch) -> None:
    inserted = _capture_template_insert(monkeypatch)

    await ChatService.create_template(
        name="Research",
        created_by="owner",
        default_model="gpt-5.6-sol",
    )

    assert inserted[0][_DEFAULT_MODEL_ARG] == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_title_generation_uses_the_everyday_role_model(monkeypatch) -> None:
    recorded: dict = {}

    async def fake_generate_response(**kwargs):
        recorded.update(kwargs)
        return {"content": "Generated title"}

    monkeypatch.setattr(
        chat_llm_service.chat_llm_service,
        "generate_response",
        fake_generate_response,
    )

    title = await ChatService.generate_title("conversation-1", "hello there")

    assert title == "Generated title"
    assert recorded["model_name"] == _EVERYDAY


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
        anthropic_client_module,
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
    assert sdk_calls[0]["model"] == _EVERYDAY
    assert sdk_calls[0]["thinking"] == {"type": "adaptive"}
    assert "temperature" not in sdk_calls[0]
    assert events[0] == {
        "type": "start",
        "model": _EVERYDAY,
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
        anthropic_client_module,
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
