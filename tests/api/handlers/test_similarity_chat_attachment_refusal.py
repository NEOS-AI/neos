"""N8 리뷰 Finding 3 — 유사도 채팅(non-streaming)도 첨부 거부를 422로 낸다.

`chat_handlers.py` 는 이미 `AttachmentNotSupportedError` 를 422로 매핑한다.
`similarity_chat_handlers.py` 의 세 non-streaming 엔드포인트는 그 매핑이
없어 500으로 새던 것을 고쳤다.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import similarity_chat_handlers
from neos.services.attachment_blocks import AttachmentNotSupportedError


def _user(user_id: str = "owner"):
    return SimpleNamespace(user_id=user_id, is_active=True)


def _conversation():
    return {"conversation_id": "c1", "user_id": "owner", "visibility": "private"}


def _app():
    app = FastAPI()
    app.include_router(similarity_chat_handlers.router, prefix="/api/v1/chat")
    app.dependency_overrides[get_current_active_user] = lambda: _user()
    return app


NON_STREAMING_PATHS_AND_PROCESSORS = [
    (
        "/api/v1/chat/conversations/c1/messages/similarity",
        "SimilarityChatProcessor",
    ),
    (
        "/api/v1/chat/conversations/c1/messages/similarity/cross-conversation",
        "cross_conversation_similarity_processor",
    ),
    (
        "/api/v1/chat/conversations/c1/messages/similarity/high-confidence",
        "high_confidence_similarity_processor",
    ),
]


@pytest.mark.parametrize("path,processor_attr", NON_STREAMING_PATHS_AND_PROCESSORS)
def test_attachment_refusal_maps_to_422_not_500(monkeypatch, path, processor_attr):
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation",
        AsyncMock(return_value=_conversation()),
    )

    refuse = AsyncMock(
        side_effect=AttachmentNotSupportedError(
            model="blind-model",
            items=[{"name": "scan.png", "mime": "image/png", "reason": "vision_unsupported"}],
        )
    )

    if processor_attr == "SimilarityChatProcessor":
        instance = SimpleNamespace(process_message=refuse)
        monkeypatch.setattr(
            similarity_chat_handlers,
            "SimilarityChatProcessor",
            lambda **kwargs: instance,
        )
    else:
        monkeypatch.setattr(
            getattr(similarity_chat_handlers, processor_attr),
            "process_message",
            refuse,
        )

    with TestClient(_app()) as client:
        response = client.post(path, json={"content": "봐줘"})

    assert response.status_code == 422
    assert "scan.png" in response.json()["detail"]
