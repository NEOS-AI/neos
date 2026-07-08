import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import similarity_chat_handlers


def _user(user_id: str = "owner"):
    return SimpleNamespace(user_id=user_id, is_active=True)


def _conversation(
    *,
    conversation_id: str = "c1",
    user_id: str = "owner",
    visibility: str = "private",
):
    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "visibility": visibility,
    }


def _message(*, message_id: str = "p1", conversation_id: str = "c1"):
    return {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "role": "user",
        "content": "parent",
        "sequence_number": 1,
        "status": "completed",
        "created_at": "2026-07-01T00:00:00",
        "updated_at": "2026-07-01T00:00:00",
    }


def _result():
    return {
        "user_message": {
            **_message(message_id="u1"),
            "content": "hello",
        },
        "assistant_message": {
            **_message(message_id="a1"),
            "role": "assistant",
            "content": "answer",
            "sequence_number": 2,
        },
        "processing_metadata": {
            "context_enhanced": False,
            "relevant_message_count": 0,
            "similarity_scores": [],
            "search_config": {},
        },
    }


def _app(current_user=None):
    app = FastAPI()
    app.include_router(similarity_chat_handlers.router, prefix="/api/v1/chat")
    if current_user is None:
        async def unauthenticated():
            raise HTTPException(status_code=401, detail="Authentication required")

        app.dependency_overrides[get_current_active_user] = unauthenticated
    else:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
    return app


MUTATION_PATHS = [
    "/api/v1/chat/conversations/c1/messages/similarity",
    "/api/v1/chat/conversations/c1/messages/similarity/stream",
    "/api/v1/chat/conversations/c1/messages/similarity/cross-conversation",
    "/api/v1/chat/conversations/c1/messages/similarity/high-confidence",
]

READ_PATHS = [
    "/api/v1/chat/conversations/c1/similarity/config",
    "/api/v1/chat/conversations/c1/similarity/analytics",
]


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", path) for path in MUTATION_PATHS]
    + [("GET", path) for path in READ_PATHS],
)
def test_similarity_routes_reject_unauthenticated_before_resource_or_processing(
    monkeypatch,
    method,
    path,
):
    get_conversation = AsyncMock()
    process = AsyncMock()
    get_messages = AsyncMock()
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation",
        get_conversation,
    )
    monkeypatch.setattr(
        similarity_chat_handlers.similarity_chat_processor,
        "process_message",
        process,
    )
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation_messages",
        get_messages,
    )

    with TestClient(_app()) as client:
        response = client.request(
            method,
            path,
            json={"content": "hello"} if method == "POST" else None,
        )

    assert response.status_code == 401
    get_conversation.assert_not_awaited()
    process.assert_not_awaited()
    get_messages.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", path) for path in MUTATION_PATHS]
    + [("GET", path) for path in READ_PATHS],
)
@pytest.mark.parametrize(
    "conversation",
    [
        None,
        _conversation(user_id="other", visibility="private"),
        _conversation(user_id="other", visibility="public"),
    ],
)
def test_similarity_routes_hide_missing_and_foreign_resources(
    monkeypatch,
    method,
    path,
    conversation,
):
    get_conversation = AsyncMock(return_value=conversation)
    get_messages = AsyncMock()
    processor = Mock()
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation",
        get_conversation,
    )
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation_messages",
        get_messages,
    )
    monkeypatch.setattr(similarity_chat_handlers, "SimilarityChatProcessor", processor)

    with TestClient(_app(_user())) as client:
        response = client.request(
            method,
            path,
            json={"content": "hello"} if method == "POST" else None,
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    processor.assert_not_called()
    get_messages.assert_not_awaited()


@pytest.mark.parametrize("path", MUTATION_PATHS)
def test_similarity_mutations_reject_parent_outside_authorized_conversation_before_processor(
    monkeypatch,
    path,
):
    conversations = {
        "c1": _conversation(),
        "c2": _conversation(conversation_id="c2"),
    }
    get_conversation = AsyncMock(
        side_effect=lambda conversation_id: conversations.get(conversation_id)
    )
    get_message = AsyncMock(return_value=_message(conversation_id="c2"))
    processor = Mock()
    cross_process = AsyncMock()
    high_process = AsyncMock()
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation",
        get_conversation,
    )
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_message",
        get_message,
    )
    monkeypatch.setattr(similarity_chat_handlers, "SimilarityChatProcessor", processor)
    monkeypatch.setattr(
        similarity_chat_handlers.cross_conversation_similarity_processor,
        "process_message",
        cross_process,
    )
    monkeypatch.setattr(
        similarity_chat_handlers.high_confidence_similarity_processor,
        "process_message",
        high_process,
    )

    with TestClient(_app(_user())) as client:
        response = client.post(
            path,
            json={"content": "hello", "parent_message_id": "p1"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    processor.assert_not_called()
    cross_process.assert_not_awaited()
    high_process.assert_not_awaited()


def test_similarity_mutation_uses_authenticated_identity(monkeypatch):
    processor_instance = SimpleNamespace(process_message=AsyncMock(return_value=_result()))
    processor_factory = Mock(return_value=processor_instance)
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_conversation",
        AsyncMock(return_value=_conversation()),
    )
    monkeypatch.setattr(
        similarity_chat_handlers.ChatService,
        "get_message",
        AsyncMock(return_value=_message()),
    )
    monkeypatch.setattr(
        similarity_chat_handlers,
        "SimilarityChatProcessor",
        processor_factory,
    )

    with TestClient(_app(_user())) as client:
        response = client.post(
            MUTATION_PATHS[0],
            json={"content": "hello", "parent_message_id": "p1"},
        )

    assert response.status_code == 200
    assert processor_instance.process_message.await_args.kwargs["user_id"] == "owner"
    assert (
        processor_instance.process_message.await_args.kwargs["parent_message_id"]
        == "p1"
    )
