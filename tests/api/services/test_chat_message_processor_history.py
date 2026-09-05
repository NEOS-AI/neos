import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services import chat_message_processor
from neos.api.services.standard_chat_processor import StandardChatProcessor


def _conversation():
    return {
        "model_name": "gpt-4o-mini",
        "system_prompt": "",
        "temperature": 0.7,
        "max_tokens": None,
    }


@pytest.mark.parametrize(
    ("history", "expected_messages"),
    [
        (
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's up?"},
            ],
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's up?"},
            ],
        ),
        (
            [{"role": "user", "content": "what's up?"}],
            [{"role": "user", "content": "what's up?"}],
        ),
    ],
    ids=["history-tail-already-user-turn", "first-turn-conversation"],
)
@pytest.mark.asyncio
async def test_generate_llm_response_sends_history_tail_user_turn_once(
    monkeypatch,
    history,
    expected_messages,
):
    """History가 이미 방금 저장한 유저 턴으로 끝나므로, `user_content`로 다시
    append하면 중복된다 — chat_llm_service에 실제로 전달된 배열로 검증한다."""
    generate_response = AsyncMock(
        return_value={
            "content": "answer",
            "model_name": "gpt-4o-mini",
            "provider": "openai",
            "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            "cost": {"total_cost": 0},
            "latency_ms": 1,
            "finish_reason": "stop",
        }
    )
    monkeypatch.setattr(
        chat_message_processor.chat_llm_service, "generate_response", generate_response
    )
    processor = StandardChatProcessor()

    await processor.generate_llm_response(
        conversation_id="c1",
        assistant_message_id="a1",
        user_content="what's up?",
        history_messages=history,
        conversation=_conversation(),
        context_data={"enhanced_system_prompt": None},
    )

    sent_messages = generate_response.await_args.kwargs["conversation_messages"]
    user_turns = [m for m in sent_messages if m.get("content") == "what's up?"]
    assert len(user_turns) == 1, (
        f"expected the user turn exactly once, found {len(user_turns)} in {sent_messages!r}"
    )
    assert sent_messages == expected_messages


@pytest.mark.parametrize(
    ("history", "expected_messages"),
    [
        (
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's up?"},
            ],
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's up?"},
            ],
        ),
        (
            [{"role": "user", "content": "what's up?"}],
            [{"role": "user", "content": "what's up?"}],
        ),
    ],
    ids=["history-tail-already-user-turn", "first-turn-conversation"],
)
@pytest.mark.asyncio
async def test_generate_llm_response_stream_sends_history_tail_user_turn_once(
    monkeypatch,
    history,
    expected_messages,
):
    """스트리밍 경로도 동일한 중복 결함을 갖는다 — 실제로 전달된 배열로 검증한다."""
    captured = {}

    async def fake_stream(**kwargs):
        captured["conversation_messages"] = kwargs["conversation_messages"]
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(
        chat_message_processor.chat_llm_service,
        "generate_response_stream",
        fake_stream,
    )
    processor = StandardChatProcessor()

    async for _ in processor.generate_llm_response_stream(
        conversation_id="c1",
        assistant_message_id="a1",
        user_content="what's up?",
        history_messages=history,
        conversation=_conversation(),
        context_data={"enhanced_system_prompt": None},
    ):
        pass

    sent_messages = captured["conversation_messages"]
    user_turns = [m for m in sent_messages if m.get("content") == "what's up?"]
    assert len(user_turns) == 1, (
        f"expected the user turn exactly once, found {len(user_turns)} in {sent_messages!r}"
    )
    assert sent_messages == expected_messages
