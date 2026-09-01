import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services.chat_stream_pipeline import ChatStreamPipeline
from neos.services.chat_llm_service import ChatLLMService


def _cost_response() -> dict[str, Decimal]:
    return {
        "input_cost": Decimal("0.00003"),
        "output_cost": Decimal("0.000075"),
        "cache_creation_cost": Decimal("0.00375"),
        "cache_read_cost": Decimal("0"),
        "total_cost": Decimal("0.003855"),
        "input_price_per_1m": Decimal("3"),
        "output_price_per_1m": Decimal("15"),
    }


def _anthropic_response() -> AIMessage:
    return AIMessage(
        content="answer",
        id="msg_test",
        response_metadata={
            "id": "msg_test",
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 1000,
                "cache_read_input_tokens": 0,
                "output_tokens": 5,
            },
        },
    )


@pytest.mark.asyncio
async def test_anthropic_invoke_receives_automatic_cache_control():
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=_anthropic_response()))
    calculate_cost = AsyncMock(return_value=_cost_response())

    with patch(
        "neos.services.chat_llm_service.create_llm", return_value=llm
    ), patch(
        "neos.services.chat_llm_service.cost_calculator.calculate_cost",
        new=calculate_cost,
    ):
        result = await ChatLLMService().generate_response(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "hello"}],
            model_name="claude-sonnet-4-6",
            enable_context_optimization=False,
        )

    assert llm.ainvoke.await_args.kwargs["cache_control"] == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert result["usage"] == {
        "prompt_tokens": 10,
        "cache_creation_tokens": 1000,
        "cache_read_tokens": 0,
        "total_input_tokens": 1010,
        "completion_tokens": 5,
        "total_tokens": 1015,
        "cache_status": "write",
        "iterations": [],
    }
    calculate_cost.assert_awaited_once_with(
        provider="anthropic",
        model_name="claude-sonnet-4-6",
        prompt_tokens=10,
        completion_tokens=5,
        cache_creation_tokens=1000,
        cache_read_tokens=0,
        cache_ttl="5m",
    )


@pytest.mark.asyncio
async def test_openai_invoke_does_not_receive_anthropic_cache_control():
    response = AIMessage(
        content="answer",
        id="chatcmpl_test",
        response_metadata={
            "token_usage": {
                "completion_tokens": 5,
                "prompt_tokens": 10,
                "total_tokens": 15,
            },
            "model_name": "gpt-4o",
            "system_fingerprint": "fp_test",
            "finish_reason": "stop",
        },
    )
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
    calculate_cost = AsyncMock(return_value=_cost_response())

    with patch(
        "neos.services.chat_llm_service.create_llm", return_value=llm
    ), patch(
        "neos.services.chat_llm_service.cost_calculator.calculate_cost",
        new=calculate_cost,
    ):
        result = await ChatLLMService().generate_response(
            conversation_id="c",
            message_id="m",
            conversation_messages=[{"role": "user", "content": "hello"}],
            model_name="gpt-4o",
            enable_context_optimization=False,
        )

    assert "cache_control" not in llm.ainvoke.await_args.kwargs
    assert result["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    calculate_cost.assert_awaited_once_with(
        provider="openai",
        model_name="gpt-4o",
        prompt_tokens=10,
        completion_tokens=5,
    )


async def _langchain_chunks():
    yield AIMessageChunk(
        content="answer",
        id="msg_stream_test",
        response_metadata={
            "id": "msg_stream_test",
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1000,
                "output_tokens": 5,
            },
        },
    )


async def _langchain_usage_metadata_chunks():
    yield AIMessageChunk(
        content="answer",
        response_metadata={"model_provider": "anthropic"},
    )
    yield AIMessageChunk(
        content="",
        response_metadata={
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "model_provider": "anthropic",
        },
        usage_metadata={
            "input_tokens": 1010,
            "output_tokens": 5,
            "total_tokens": 1015,
            "input_token_details": {
                "cache_creation": 0,
                "cache_read": 1000,
            },
        },
        chunk_position="last",
    )


@pytest.mark.asyncio
async def test_anthropic_langchain_stream_receives_automatic_cache_control():
    llm = SimpleNamespace(
        astream=MagicMock(
            side_effect=lambda *args, **kwargs: _langchain_chunks()
        )
    )
    calculate_cost = AsyncMock(return_value=_cost_response())

    with patch(
        "neos.services.chat_llm_service.create_llm", return_value=llm
    ), patch(
        "neos.services.chat_llm_service.cost_calculator.calculate_cost",
        new=calculate_cost,
    ):
        events = [
            event
            async for event in ChatLLMService().generate_response_stream(
                conversation_id="c",
                message_id="m",
                conversation_messages=[{"role": "user", "content": "hello"}],
                model_name="claude-sonnet-4-6",
                enable_context_optimization=False,
            )
        ]

    assert llm.astream.call_args.kwargs["cache_control"] == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert events[-1]["type"] == "complete"
    assert events[-1]["usage"]["cache_read_tokens"] == 1000
    assert events[-1]["usage"]["total_input_tokens"] == 1010
    assert events[-1]["usage"]["cache_status"] == "hit"
    calculate_cost.assert_awaited_once_with(
        provider="anthropic",
        model_name="claude-sonnet-4-6",
        prompt_tokens=10,
        completion_tokens=5,
        cache_creation_tokens=0,
        cache_read_tokens=1000,
        cache_ttl="5m",
    )


@pytest.mark.asyncio
async def test_anthropic_langchain_stream_reads_real_usage_metadata_shape():
    llm = SimpleNamespace(
        astream=MagicMock(
            side_effect=lambda *args, **kwargs: _langchain_usage_metadata_chunks()
        )
    )
    calculate_cost = AsyncMock(return_value=_cost_response())

    with patch(
        "neos.services.chat_llm_service.create_llm", return_value=llm
    ), patch(
        "neos.services.chat_llm_service.cost_calculator.calculate_cost",
        new=calculate_cost,
    ):
        events = [
            event
            async for event in ChatLLMService().generate_response_stream(
                conversation_id="c",
                message_id="m",
                conversation_messages=[{"role": "user", "content": "hello"}],
                model_name="claude-sonnet-4-6",
                enable_context_optimization=False,
            )
        ]

    assert events[-1]["type"] == "complete"
    assert events[-1]["usage"] == {
        "prompt_tokens": 10,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 1000,
        "total_input_tokens": 1010,
        "completion_tokens": 5,
        "total_tokens": 1015,
        "cache_status": "hit",
        "iterations": [],
    }
    calculate_cost.assert_awaited_once_with(
        provider="anthropic",
        model_name="claude-sonnet-4-6",
        prompt_tokens=10,
        completion_tokens=5,
        cache_creation_tokens=0,
        cache_read_tokens=1000,
        cache_ttl="5m",
    )


class _DirectAnthropicStream:
    def __init__(self, final_message):
        self._events = iter(
            [
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text="answer"),
                )
            ]
        )
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def get_final_message(self):
        return self._final_message


@pytest.mark.asyncio
async def test_direct_anthropic_tool_stream_receives_automatic_cache_control():
    final_message = SimpleNamespace(
        id="msg_tool_test",
        model="claude-sonnet-4-6",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        content=[SimpleNamespace(type="text", text="answer")],
        usage=SimpleNamespace(
            input_tokens=10,
            cache_creation_input_tokens=1000,
            cache_read_input_tokens=0,
            output_tokens=5,
        ),
    )
    direct_stream = _DirectAnthropicStream(final_message)
    stream_call = MagicMock(return_value=direct_stream)
    client = SimpleNamespace(messages=SimpleNamespace(stream=stream_call))
    calculate_cost = AsyncMock(return_value=_cost_response())

    with patch(
        "neos.utils.anthropic_client.AsyncAnthropic",
        return_value=client,
    ), patch(
        "neos.services.chat_llm_service.cost_calculator.calculate_cost",
        new=calculate_cost,
    ):
        events = [
            event
            async for event in ChatLLMService().generate_response_stream_with_tools(
                conversation_id="c",
                message_id="m",
                conversation_messages=[{"role": "user", "content": "hello"}],
                tools=[
                    {
                        "name": "lookup",
                        "description": "Look up a value",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                        },
                    }
                ],
                model_name="claude-sonnet-4-6",
            )
        ]

    assert stream_call.call_args.kwargs["cache_control"] == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert events[-1]["usage"]["cache_creation_tokens"] == 1000
    assert events[-1]["usage"]["total_input_tokens"] == 1010
    calculate_cost.assert_awaited_once_with(
        provider="anthropic",
        model_name="claude-sonnet-4-6",
        prompt_tokens=10,
        completion_tokens=5,
        cache_creation_tokens=1000,
        cache_read_tokens=0,
        cache_ttl="5m",
    )


class _PipelineChatStorage:
    messages: list[dict] = []

    @classmethod
    async def add_message(cls, **kwargs):
        cls.messages.append(kwargs)
        return kwargs

    @classmethod
    async def get_conversation_messages(cls, conversation_id, limit=20):
        return []


class _PipelineLLM:
    def __init__(self, *, usage=None, cost=None):
        self._usage = usage
        self._cost = cost

    async def generate_response_stream_with_tools(self, **kwargs):
        yield {
            "type": "start",
            "model": kwargs["model_name"],
            "provider": "anthropic",
        }
        yield {"type": "content", "content": "answer"}
        yield {
            "type": "complete",
            "full_content": "answer",
            "model_name": kwargs["model_name"],
            "provider": "anthropic",
            "usage": self._usage
            if self._usage is not None
            else {
                "prompt_tokens": 10,
                "cache_creation_tokens": 1000,
                "cache_read_tokens": 2000,
                "total_input_tokens": 3010,
                "completion_tokens": 5,
                "total_tokens": 3015,
                "cache_status": "hit",
                "iterations": [],
                "anthropic": {
                    "prompt_caching": {"status": "hit"},
                    "advisor": {"call_count": 1},
                },
            },
            "cost": self._cost
            if self._cost is not None
            else {
                **_cost_response(),
                "advisor_cost": Decimal("0.25"),
                "additional_cost": Decimal("0.25"),
                "advisor": {"call_count": 1},
            },
            "latency_ms": 12,
        }


@pytest.mark.parametrize(
    (
        "llm",
        "expected_cache_creation_tokens",
        "expected_cache_read_tokens",
        "expected_additional_cost",
        "expected_metadata",
    ),
    [
        pytest.param(
            _PipelineLLM(),
            1000,
            2000,
            Decimal("0.25"),
            {
                "anthropic": {
                    "prompt_caching": {"status": "hit"},
                    "advisor": {"call_count": 1},
                }
            },
            id="anthropic-cache-and-advisor-accounting",
        ),
        pytest.param(
            _PipelineLLM(
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
                cost=_cost_response(),
            ),
            0,
            0,
            0,
            {"anthropic": {}},
            id="legacy-usage-defaults",
        ),
    ],
)
@pytest.mark.asyncio
async def test_chat_pipeline_forwards_cache_and_additional_cost_to_persistence(
    monkeypatch,
    llm,
    expected_cache_creation_tokens,
    expected_cache_read_tokens,
    expected_additional_cost,
    expected_metadata,
):
    monkeypatch.setattr(
        "neos.api.services.chat_stream_pipeline.app_settings.ENABLE_WORKFLOW_IN_CHAT",
        False,
    )
    monkeypatch.setattr(
        "neos.api.services.chat_stream_strategy.app_settings.TOOL_SEARCH_ENABLED",
        False,
    )
    monkeypatch.setattr(
        "neos.api.services.chat_system_prompt_builder.app_settings.ARTIFACTS_ENABLED",
        False,
    )
    monkeypatch.setattr(
        "neos.api.services.chat_system_prompt_builder.app_settings.INLINE_VIS_ENABLED",
        False,
    )
    _PipelineChatStorage.messages = []
    record_cost = AsyncMock(return_value=_cost_response())
    pipeline = ChatStreamPipeline(
        chat_llm_service=llm,
        cost_calculator=SimpleNamespace(
            record_cost_for_existing_message=record_cost
        ),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=_PipelineChatStorage,
        multi_agent_workflow=object(),
        workflow_callback_cls=object(),
        map_node_to_agent_fn=lambda node: node,
    )
    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="hello",
        attachments=[],
        parent_message_id=None,
        metadata={},
    )

    events = [
        event
        async for event in pipeline.run(
            conversation_id="c",
            request=request,
            current_user=SimpleNamespace(user_id="u"),
            authorized_conversation={
                "conversation_id": "c",
                "user_id": "u",
                "model_name": "claude-sonnet-4-6",
                "system_prompt": "",
                "temperature": 0.7,
                "max_tokens": None,
            },
        )
    ]

    assert events[-1] == "data: [DONE]\n\n"
    persistence_kwargs = record_cost.await_args.kwargs
    assert (
        persistence_kwargs["cache_creation_tokens"]
        == expected_cache_creation_tokens
    )
    assert persistence_kwargs["cache_read_tokens"] == expected_cache_read_tokens
    assert persistence_kwargs["cache_ttl"] == "5m"
    assert persistence_kwargs["additional_cost_usd"] == expected_additional_cost
    assert persistence_kwargs["metadata"] == expected_metadata
