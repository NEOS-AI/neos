import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.handlers import rag_chat_handlers
from neos.api.models.rag_chat_models import RAGSendMessageRequest


def _add_message_side_effect():
    return [
        {
            "message_id": "u1",
            "conversation_id": "c1",
            "role": "user",
            "content": "what's new?",
            "sequence_number": 1,
        },
        {
            "message_id": "a1",
            "conversation_id": "c1",
            "role": "assistant",
            "content": "here's what's new",
            "sequence_number": 2,
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("history", "expected_messages"),
    [
        (
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's new?"},
            ],
            [
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "what's new?"},
            ],
        ),
        (
            [{"role": "user", "content": "what's new?"}],
            [{"role": "user", "content": "what's new?"}],
        ),
    ],
    ids=["history-tail-already-user-turn", "first-turn-conversation"],
)
async def test_send_rag_message_sends_history_tail_user_turn_once(
    monkeypatch,
    history,
    expected_messages,
):
    """History가 tail이 된 뒤 방금 저장한 유저 턴을 항상 포함하므로,
    수동 append는 그것을 중복시킨다 — RAG LLM 서비스에 실제로 전달된 배열로 검증한다."""
    generate_response_with_rag = AsyncMock(
        return_value={
            "content": "here's what's new",
            "model_name": "gpt-4o-mini",
            "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            "cost": {"total_cost": 0},
            "latency_ms": 1,
            "rag_context": {"relevant_messages_count": 0, "relevant_messages": []},
        }
    )
    monkeypatch.setattr(
        rag_chat_handlers.rag_chat_llm_service,
        "generate_response_with_rag",
        generate_response_with_rag,
    )
    monkeypatch.setattr(
        rag_chat_handlers.ChatService,
        "get_conversation_messages",
        AsyncMock(return_value=history),
    )
    monkeypatch.setattr(
        rag_chat_handlers.ChatService,
        "add_message",
        AsyncMock(side_effect=_add_message_side_effect()),
    )

    request = RAGSendMessageRequest(content="what's new?", enable_rag=True)
    background_tasks = BackgroundTasks()
    authorized_conversation = {
        "conversation_id": "c1",
        "user_id": "user_123",
        "system_prompt": "",
        "model_name": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": None,
    }

    await rag_chat_handlers.send_rag_message(
        "c1",
        request,
        background_tasks,
        authorized_conversation=authorized_conversation,
        current_user=SimpleNamespace(user_id="user_123", is_active=True),
    )

    sent_messages = generate_response_with_rag.await_args.kwargs["conversation_messages"]
    user_turns = [m for m in sent_messages if m.get("content") == "what's new?"]
    assert len(user_turns) == 1, (
        f"expected the user turn exactly once, found {len(user_turns)} in {sent_messages!r}"
    )
    assert sent_messages == expected_messages
