import os
from collections.abc import Iterable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    TextBlock,
    TextDelta,
    Usage,
)
from anthropic.types.beta import (
    BetaAdvisorMessageIterationUsage,
    BetaAdvisorResultBlock,
    BetaAdvisorToolResultBlock,
    BetaAdvisorToolResultError,
    BetaDirectCaller,
    BetaMessage,
    BetaMessageIterationUsage,
    BetaRawContentBlockDeltaEvent,
    BetaServerToolUseBlock,
    BetaTextBlock,
    BetaTextDelta,
    BetaToolUseBlock,
    BetaUsage,
)

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.config.schema import AdvisorConfig, PromptCachingConfig
from neos.services import chat_llm_service as chat_module
from neos.services.chat_llm_service import ChatLLMService


CORE_TOOL = {
    "name": "lookup",
    "description": "Look up a value",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


def _cost_result(total_cost: str = "0.01") -> dict[str, Decimal]:
    return {
        "input_cost": Decimal("0.001"),
        "output_cost": Decimal("0.009"),
        "cache_creation_cost": Decimal("0"),
        "cache_read_cost": Decimal("0"),
        "total_cost": Decimal(total_cost),
        "input_price_per_1m": Decimal("3"),
        "output_price_per_1m": Decimal("15"),
    }


class _ScriptedAsyncMessageStream:
    """Dependency-shaped stand-in for Anthropic's async message stream."""

    def __init__(self, final_message: Message | BetaMessage, events: Iterable[Any]):
        self._final_message = final_message
        self._events = iter(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def get_final_message(self) -> Message | BetaMessage:
        return self._final_message


class _ScriptedAsyncMessageStreamManager:
    """Matches AsyncMessageStreamManager/BetaAsyncMessageStreamManager."""

    def __init__(
        self,
        final_message: Message | BetaMessage,
        events: Iterable[Any] = (),
    ):
        self._stream = _ScriptedAsyncMessageStream(final_message, events)

    async def __aenter__(self) -> _ScriptedAsyncMessageStream:
        return self._stream

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FakeAsyncAnthropic:
    """Records stable and beta calls while returning scripted managers."""

    def __init__(
        self,
        *,
        stable: Iterable[_ScriptedAsyncMessageStreamManager] = (),
        beta: Iterable[_ScriptedAsyncMessageStreamManager] = (),
    ):
        self.messages = SimpleNamespace(stream=MagicMock(side_effect=list(stable)))
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(stream=MagicMock(side_effect=list(beta)))
        )


def _stable_message(
    *,
    content: list[Any] | None = None,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> Message:
    return Message(
        id="msg_stable",
        type="message",
        role="assistant",
        model=model,
        stop_reason="end_turn",
        stop_sequence=None,
        content=content or [TextBlock(type="text", text="answer")],
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _beta_message(
    *,
    message_id: str,
    stop_reason: str,
    content: list[Any],
    usage: BetaUsage | None = None,
) -> BetaMessage:
    return BetaMessage(
        id=message_id,
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        stop_reason=stop_reason,
        stop_sequence=None,
        content=content,
        usage=usage or BetaUsage(input_tokens=10, output_tokens=5),
    )


def _message_iteration(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> BetaMessageIterationUsage:
    return BetaMessageIterationUsage(
        type="message",
        input_tokens=input_tokens,
        cache_creation_input_tokens=cache_creation_tokens,
        cache_read_input_tokens=cache_read_tokens,
        output_tokens=output_tokens,
    )


def _advisor_iteration(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> BetaAdvisorMessageIterationUsage:
    return BetaAdvisorMessageIterationUsage(
        type="advisor_message",
        model="claude-opus-4-8",
        input_tokens=input_tokens,
        cache_creation_input_tokens=cache_creation_tokens,
        cache_read_input_tokens=cache_read_tokens,
        output_tokens=output_tokens,
    )


def _stable_text_event(text: str) -> RawContentBlockDeltaEvent:
    return RawContentBlockDeltaEvent(
        type="content_block_delta",
        index=0,
        delta=TextDelta(type="text_delta", text=text),
    )


def _beta_text_event(text: str, *, index: int = 0) -> BetaRawContentBlockDeltaEvent:
    return BetaRawContentBlockDeltaEvent(
        type="content_block_delta",
        index=index,
        delta=BetaTextDelta(type="text_delta", text=text),
    )


async def _collect_events(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: _FakeAsyncAnthropic,
    advisor: AdvisorConfig,
    model: str,
    calculator: AsyncMock | None = None,
    search_handler: Any | None = None,
    tool_executor: Any | None = None,
    max_tool_rounds: int = 3,
) -> tuple[list[dict[str, Any]], AsyncMock]:
    calculator = calculator or AsyncMock(return_value=_cost_result())
    monkeypatch.setattr(
        chat_module.anthropic,
        "AsyncAnthropic",
        MagicMock(return_value=client),
    )
    monkeypatch.setattr(chat_module.settings.config.llm, "advisor", advisor)
    monkeypatch.setattr(
        chat_module.settings.config.llm,
        "prompt_caching",
        PromptCachingConfig(enabled=True, ttl="5m"),
    )
    monkeypatch.setattr(chat_module.cost_calculator, "calculate_cost", calculator)

    handler = search_handler or SimpleNamespace(handle=AsyncMock(return_value={}))
    events = [
        event
        async for event in ChatLLMService().generate_response_stream_with_tool_search(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "hello"}],
            core_tools=[CORE_TOOL],
            search_handler=handler,
            tool_executor=tool_executor,
            model_name=model,
            max_tool_rounds=max_tool_rounds,
        )
    ]
    return events, calculator


@pytest.mark.asyncio
async def test_default_advisor_off_routes_through_stable_messages_api(monkeypatch):
    client = _FakeAsyncAnthropic(
        stable=[
            _ScriptedAsyncMessageStreamManager(
                _stable_message(),
                [_stable_text_event("answer")],
            )
        ]
    )

    events, _ = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(),
        model="claude-sonnet-4-6",
    )

    assert client.messages.stream.call_count == 1
    assert client.beta.messages.stream.call_count == 0
    kwargs = client.messages.stream.call_args.kwargs
    assert "betas" not in kwargs
    assert all(tool.get("type") != "advisor_20260301" for tool in kwargs["tools"])
    assert kwargs["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert events[-1]["type"] == "complete"
    assert events[-1]["usage"]["anthropic"]["advisor"] == {
        "enabled": False,
        "injected": False,
        "skip_reason": None,
        "call_count": 0,
        "models": [],
        "input_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
        "error_codes": [],
    }


@pytest.mark.asyncio
async def test_compatible_advisor_routes_through_beta_with_configured_tool(monkeypatch):
    final_message = _beta_message(
        message_id="msg_beta",
        stop_reason="end_turn",
        content=[BetaTextBlock(type="text", text="answer")],
        usage=BetaUsage(
            input_tokens=10,
            output_tokens=5,
            iterations=[_message_iteration(input_tokens=10, output_tokens=5)],
        ),
    )
    client = _FakeAsyncAnthropic(
        beta=[
            _ScriptedAsyncMessageStreamManager(
                final_message,
                [_beta_text_event("answer")],
            )
        ]
    )

    events, _ = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(enabled=True),
        model="claude-sonnet-4-6",
    )

    assert client.messages.stream.call_count == 0
    assert client.beta.messages.stream.call_count == 1
    kwargs = client.beta.messages.stream.call_args.kwargs
    assert kwargs["betas"] == ["advisor-tool-2026-03-01"]
    assert kwargs["tools"][-1]["type"] == "advisor_20260301"
    assert kwargs["tools"][-1]["max_uses"] == 2
    assert kwargs["tools"][-1]["max_tokens"] == 2048
    assert kwargs["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert events[-1]["usage"]["anthropic"]["advisor"]["injected"] is True


@pytest.mark.asyncio
async def test_incompatible_advisor_stays_on_stable_api_and_records_skip(monkeypatch):
    client = _FakeAsyncAnthropic(
        stable=[
            _ScriptedAsyncMessageStreamManager(
                _stable_message(model="claude-sonnet-4-5-20250929")
            )
        ]
    )

    events, _ = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(enabled=True),
        model="claude-sonnet-4-5-20250929",
    )

    assert client.messages.stream.call_count == 1
    assert client.beta.messages.stream.call_count == 0
    assert "betas" not in client.messages.stream.call_args.kwargs
    advisor_usage = events[-1]["usage"]["anthropic"]["advisor"]
    assert advisor_usage["enabled"] is True
    assert advisor_usage["injected"] is False
    assert advisor_usage["skip_reason"] == "incompatible_model_pair"


@pytest.mark.asyncio
async def test_pause_turn_resends_complete_assistant_blocks_and_aggregates_usage(
    monkeypatch,
):
    pause_message = _beta_message(
        message_id="msg_pause",
        stop_reason="pause_turn",
        content=[
            BetaServerToolUseBlock(
                type="server_tool_use",
                id="srv_1",
                name="advisor",
                input={"question": "check the plan"},
                caller=BetaDirectCaller(type="direct"),
            )
        ],
        usage=BetaUsage(
            input_tokens=10,
            cache_creation_input_tokens=100,
            cache_read_input_tokens=0,
            output_tokens=1,
        ),
    )
    final_message = _beta_message(
        message_id="msg_complete",
        stop_reason="end_turn",
        content=[
            BetaAdvisorToolResultBlock(
                type="advisor_tool_result",
                tool_use_id="srv_1",
                content=BetaAdvisorResultBlock(
                    type="advisor_result",
                    text="internal guidance that must not be emitted",
                ),
            ),
            BetaTextBlock(type="text", text="answer"),
        ],
        usage=BetaUsage(
            input_tokens=20,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=200,
            output_tokens=2,
            iterations=[
                _message_iteration(
                    input_tokens=20,
                    cache_read_tokens=200,
                    output_tokens=2,
                ),
                _advisor_iteration(
                    input_tokens=30,
                    cache_creation_tokens=40,
                    cache_read_tokens=50,
                    output_tokens=4,
                ),
            ],
        ),
    )
    client = _FakeAsyncAnthropic(
        beta=[
            _ScriptedAsyncMessageStreamManager(pause_message),
            _ScriptedAsyncMessageStreamManager(
                final_message,
                [_beta_text_event("answer", index=1)],
            ),
        ]
    )

    def price_by_model(**kwargs):
        if kwargs["model_name"] == "claude-opus-4-8":
            return _cost_result("0.40")
        return _cost_result("0.10")

    calculator = AsyncMock(side_effect=price_by_model)
    events, _ = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(
            enabled=True,
            prompt_caching={"enabled": True, "ttl": "1h"},
        ),
        model="claude-sonnet-4-6",
        calculator=calculator,
        max_tool_rounds=1,
    )

    assert client.beta.messages.stream.call_count == 2
    second_messages = client.beta.messages.stream.call_args_list[1].kwargs["messages"]
    assert second_messages[-1]["role"] == "assistant"
    assert second_messages[-1]["content"] == [
        {
            "id": "srv_1",
            "input": {"question": "check the plan"},
            "name": "advisor",
            "type": "server_tool_use",
            "caller": {"type": "direct"},
        }
    ]
    first_call = client.beta.messages.stream.call_args_list[0].kwargs
    second_call = client.beta.messages.stream.call_args_list[1].kwargs
    assert first_call["tools"] == second_call["tools"]
    assert first_call["betas"] == second_call["betas"]

    assert not any(
        event.get("content") == "internal guidance that must not be emitted"
        for event in events
    )
    complete = events[-1]
    assert complete["type"] == "complete"
    assert complete["tool_search_rounds"] == 1
    assert complete["usage"]["prompt_tokens"] == 30
    assert complete["usage"]["cache_creation_tokens"] == 100
    assert complete["usage"]["cache_read_tokens"] == 200
    assert complete["usage"]["completion_tokens"] == 3
    assert complete["usage"]["total_tokens"] == 333
    assert complete["usage"]["anthropic"]["prompt_caching"] == {"status": "hit"}
    assert complete["usage"]["anthropic"]["advisor"] == {
        "enabled": True,
        "injected": True,
        "skip_reason": None,
        "call_count": 1,
        "models": ["claude-opus-4-8"],
        "input_tokens": 30,
        "cache_creation_tokens": 40,
        "cache_read_tokens": 50,
        "output_tokens": 4,
        "error_codes": [],
    }
    assert complete["cost"]["total_cost"] == Decimal("0.60")
    assert complete["cost"]["advisor_cost"] == Decimal("0.40")
    assert complete["cost"]["additional_cost"] == Decimal("0.50")
    assert calculator.await_count == 4
    assert calculator.await_args_list[-1].kwargs == {
        "provider": "anthropic",
        "model_name": "claude-opus-4-8",
        "prompt_tokens": 30,
        "completion_tokens": 4,
        "cache_creation_tokens": 40,
        "cache_read_tokens": 50,
        "cache_ttl": "1h",
    }


@pytest.mark.asyncio
async def test_pause_turn_exceeding_configured_limit_yields_one_error(monkeypatch):
    pauses = [
        _ScriptedAsyncMessageStreamManager(
            _beta_message(
                message_id=f"msg_pause_{index}",
                stop_reason="pause_turn",
                content=[
                    BetaServerToolUseBlock(
                        type="server_tool_use",
                        id=f"srv_{index}",
                        name="advisor",
                        input={"attempt": index},
                    )
                ],
            )
        )
        for index in range(4)
    ]
    client = _FakeAsyncAnthropic(beta=pauses)

    events, calculator = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(enabled=True),
        model="claude-sonnet-4-6",
        max_tool_rounds=1,
    )

    assert client.beta.messages.stream.call_count == 4
    assert events == [
        {"type": "start", "model": "claude-sonnet-4-6", "provider": "anthropic"},
        {
            "type": "error",
            "error": "Anthropic Advisor pause_turn exceeded configured limit (3)",
        },
    ]
    calculator.assert_not_awaited()


@pytest.mark.asyncio
async def test_advisor_result_error_is_preserved_and_recorded_without_exposure(
    monkeypatch,
):
    first_message = _beta_message(
        message_id="msg_error_result",
        stop_reason="tool_use",
        content=[
            BetaAdvisorToolResultBlock(
                type="advisor_tool_result",
                tool_use_id="srv_1",
                content=BetaAdvisorToolResultError(
                    type="advisor_tool_result_error",
                    error_code="overloaded",
                ),
            ),
            BetaToolUseBlock(
                type="tool_use",
                id="tool_1",
                name="lookup",
                input={"query": "value"},
            ),
        ],
        usage=BetaUsage(
            input_tokens=10,
            output_tokens=2,
            iterations=[
                _message_iteration(input_tokens=10, output_tokens=2),
                _advisor_iteration(input_tokens=20, output_tokens=1),
            ],
        ),
    )
    second_message = _beta_message(
        message_id="msg_after_error",
        stop_reason="end_turn",
        content=[BetaTextBlock(type="text", text="recovered")],
        usage=BetaUsage(
            input_tokens=5,
            output_tokens=1,
            iterations=[_message_iteration(input_tokens=5, output_tokens=1)],
        ),
    )
    client = _FakeAsyncAnthropic(
        beta=[
            _ScriptedAsyncMessageStreamManager(first_message),
            _ScriptedAsyncMessageStreamManager(
                second_message,
                [_beta_text_event("recovered")],
            ),
        ]
    )
    tool_executor = AsyncMock(return_value={"value": 42})

    events, _ = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(enabled=True),
        model="claude-sonnet-4-6",
        tool_executor=tool_executor,
    )

    second_messages = client.beta.messages.stream.call_args_list[1].kwargs["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["content"][0] == {
        "content": {
            "error_code": "overloaded",
            "type": "advisor_tool_result_error",
        },
        "tool_use_id": "srv_1",
        "type": "advisor_tool_result",
    }
    assert events[-1]["usage"]["anthropic"]["advisor"]["call_count"] == 1
    assert events[-1]["usage"]["anthropic"]["advisor"]["error_codes"] == [
        "overloaded"
    ]
    assert not any("overloaded" in str(event.get("content", "")) for event in events)


@pytest.mark.asyncio
async def test_beta_bad_request_surfaces_model_pair_and_never_retries_stable(
    monkeypatch,
):
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://api.anthropic.test/v1/messages"),
    )
    error = anthropic.BadRequestError(
        "advisor beta rejected",
        response=response,
        body={"error": {"message": "advisor beta rejected"}},
    )
    client = _FakeAsyncAnthropic(
        stable=[_ScriptedAsyncMessageStreamManager(_stable_message())]
    )
    client.beta.messages.stream.side_effect = error

    events, calculator = await _collect_events(
        monkeypatch,
        client=client,
        advisor=AdvisorConfig(enabled=True),
        model="claude-sonnet-4-6",
    )

    assert client.beta.messages.stream.call_count == 1
    assert client.messages.stream.call_count == 0
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "error"
    assert "Anthropic Advisor beta API" in events[-1]["error"]
    assert "executor=claude-sonnet-4-6" in events[-1]["error"]
    assert "advisor=claude-opus-4-8" in events[-1]["error"]
    calculator.assert_not_awaited()
