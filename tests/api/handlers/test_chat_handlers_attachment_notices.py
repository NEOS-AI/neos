"""N8 리뷰 Finding 4 — non-streaming 핸들러가 attachment_notices 를 계산해
놓고 저장하지 않던 결함.

`generate_response` 가 돌려주는 `attachment_notices` 를 스트리밍 경로
(`chat_stream_pipeline.py`)는 저장 메타데이터에 싣지만, `send_message` 와
`regenerate_message` 는 읽지 않고 버렸다. 두 핸들러 모두 값이 있을 때만
`attachment_notices` 를 어시스턴트 메시지 메타데이터에 넣는지 확인한다.
"""

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.handlers import chat_handlers
from neos.api.models.chat_models import (
    MessageRole,
    MessageStatus,
    RegenerateMessageRequest,
    SendMessageRequest,
)


def _llm_response(*, with_notices: bool):
    response = {
        "content": "answer",
        "model_name": "claude-sonnet-5",
        "provider": "anthropic",
        "usage": {"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 1},
        "cost": {"total_cost": 0.001},
        "latency_ms": 42,
        "finish_reason": "stop",
    }
    if with_notices:
        response["attachment_notices"] = ["old.png: 길이 상한으로 제외됨"]
    return response


def _stored_message(**overrides):
    base = {
        "message_id": "m1",
        "conversation_id": "c1",
        "role": "user",
        "content": "hi",
        "content_type": "text",
        "sequence_number": 1,
        "status": MessageStatus.COMPLETED,
        "created_at": "2026-07-01T00:00:00",
        "updated_at": "2026-07-01T00:00:00",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
@pytest.mark.parametrize("with_notices", [True, False])
async def test_send_message_persists_attachment_notices_only_when_present(
    monkeypatch, with_notices
):
    captured_metadata = {}

    async def fake_add_message(*, role, metadata=None, **kwargs):
        if role == "assistant":
            captured_metadata.update(metadata or {})
        return _stored_message(role=role, message_id=f"{role}-1")

    monkeypatch.setattr(chat_handlers.ChatService, "add_message", fake_add_message)
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation",
        AsyncMock(return_value={"model_name": "claude-sonnet-5", "system_prompt": "", "temperature": 0.7, "max_tokens": None}),
    )
    monkeypatch.setattr(
        chat_handlers.chat_llm_service,
        "generate_response",
        AsyncMock(return_value=_llm_response(with_notices=with_notices)),
    )
    monkeypatch.setattr(
        chat_handlers.cost_calculator,
        "record_cost_for_existing_message",
        AsyncMock(),
    )

    request = SendMessageRequest(content="hi", role=MessageRole.USER)

    await chat_handlers.send_message(
        conversation_id="c1",
        request=request,
        current_user=None,
        authorized_conversation={"conversation_id": "c1", "user_id": "u1"},
    )

    if with_notices:
        assert captured_metadata.get("attachment_notices") == [
            "old.png: 길이 상한으로 제외됨"
        ]
    else:
        assert "attachment_notices" not in captured_metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("with_notices", [True, False])
async def test_regenerate_message_persists_attachment_notices_only_when_present(
    monkeypatch, with_notices
):
    captured_metadata = {}

    async def fake_add_message(*, role, metadata=None, **kwargs):
        captured_metadata.update(metadata or {})
        return _stored_message(role=role, message_id="new-1")

    monkeypatch.setattr(chat_handlers.ChatService, "add_message", fake_add_message)
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation",
        AsyncMock(return_value={"model_name": "claude-sonnet-5", "system_prompt": "", "temperature": 0.7, "max_tokens": None}),
    )
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation_messages",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        chat_handlers.chat_llm_service,
        "generate_response",
        AsyncMock(return_value=_llm_response(with_notices=with_notices)),
    )
    monkeypatch.setattr(
        chat_handlers.cost_calculator,
        "record_cost_for_existing_message",
        AsyncMock(),
    )

    request = RegenerateMessageRequest(message_id="orig-1")
    original_message = _stored_message(
        message_id="orig-1", role="assistant", sequence_number=2
    )

    await chat_handlers.regenerate_message(
        message_id="orig-1",
        request=request,
        original_message=original_message,
    )

    if with_notices:
        assert captured_metadata.get("attachment_notices") == [
            "old.png: 길이 상한으로 제외됨"
        ]
    else:
        assert "attachment_notices" not in captured_metadata
