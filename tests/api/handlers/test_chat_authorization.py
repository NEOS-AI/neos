from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import chat_handlers
from neos.api.models.chat_models import CreateConversationRequest
from neos.database.connection import get_db


def _conversation() -> dict:
    return {
        "conversation_id": "c1",
        "user_id": "owner",
        "title": "New chat",
        "summary": None,
        "model_name": "claude-sonnet-4-5-20250929",
        "model_version": None,
        "system_prompt": None,
        "temperature": 0.7,
        "max_tokens": None,
        "mode": "standard",
        "status": "active",
        "is_pinned": False,
        "is_shared": False,
        "share_token": None,
        "visibility": "private",
        "message_count": 0,
        "total_tokens_used": 0,
        "total_cost": 0.0,
        "last_message_at": None,
        "last_accessed_at": None,
        "created_at": "2026-07-01T00:00:00",
        "updated_at": "2026-07-01T00:00:00",
        "tags": [],
        "metadata": {},
    }


def _route(path: str, method: str) -> APIRoute:
    routes = [route for route in chat_handlers.router.routes if isinstance(route, APIRoute)]
    return next(route for route in routes if route.path == path and method in route.methods)


def _analytics() -> dict:
    return {
        "conversation_id": "c1",
        "analysis_period": "session",
        "period_start": "2026-07-01T00:00:00",
        "period_end": "2026-07-01T01:00:00",
        "total_messages": 3,
        "user_messages": 2,
        "assistant_messages": 1,
        "total_tokens_used": 100,
        "prompt_tokens_used": 60,
        "completion_tokens_used": 40,
        "estimated_cost": 0.01,
        "average_response_time_ms": 250,
        "average_message_length": 42,
        "average_quality_score": 0.9,
        "tools_used": [],
        "tool_call_count": 0,
        "positive_feedback_count": 1,
        "negative_feedback_count": 0,
        "messages_edited_count": 0,
    }


def _analytics_app(current_user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_handlers.router)

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
    return app


def test_create_conversation_request_accepts_omitted_deprecated_user_id():
    request = CreateConversationRequest(conversation_id="c1")

    assert request.user_id is None


@pytest.mark.asyncio
async def test_create_conversation_uses_authenticated_user(monkeypatch):
    create = AsyncMock(return_value=_conversation())
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)
    request = CreateConversationRequest(user_id="attacker", conversation_id="c1")

    await chat_handlers.create_conversation(
        request,
        current_user=SimpleNamespace(user_id="owner", is_active=True),
    )

    assert create.await_args.kwargs["user_id"] == "owner"


def test_conversation_routes_declare_access_dependencies():
    expected = {
        ("/conversations/{conversation_id}", "GET"): "get_readable_conversation",
        ("/conversations/{conversation_id}/full", "GET"): "get_readable_conversation",
        ("/conversations/{conversation_id}", "PATCH"): "get_owned_conversation",
        ("/conversations/{conversation_id}", "DELETE"): "get_owned_conversation",
        ("/conversations/{conversation_id}/archive", "POST"): "get_owned_conversation",
        ("/conversations/{conversation_id}/generate-title", "POST"): "get_owned_conversation",
        ("/conversations/{conversation_id}/messages/after", "DELETE"): "get_owned_conversation",
        ("/conversations/{conversation_id}/analytics", "GET"): "get_readable_conversation",
    }

    for (path, method), dependency_name in expected.items():
        names = {
            dependency.call.__name__
            for dependency in _route(path, method).dependant.dependencies
        }
        assert dependency_name in names


def test_conversation_analytics_rejects_unauthenticated_before_service(monkeypatch):
    get_conversation = AsyncMock(return_value=_conversation())
    get_analytics = AsyncMock(return_value=_analytics())
    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation_analytics",
        get_analytics,
    )

    with TestClient(_analytics_app()) as client:
        response = client.get("/conversations/c1/analytics")

    assert response.status_code == 401
    get_conversation.assert_not_awaited()
    get_analytics.assert_not_awaited()


def test_conversation_analytics_hides_private_non_owner_and_missing(monkeypatch):
    get_conversation = AsyncMock(
        side_effect=[
            {
                "conversation_id": "private",
                "user_id": "other",
                "visibility": "private",
            },
            None,
        ]
    )
    get_analytics = AsyncMock(return_value=_analytics())
    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation_analytics",
        get_analytics,
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_analytics_app(current_user)) as client:
        private_response = client.get("/conversations/private/analytics")
        missing_response = client.get("/conversations/missing/analytics")

    expected = {"detail": "Resource not found"}
    assert private_response.status_code == missing_response.status_code == 404
    assert private_response.json() == missing_response.json() == expected
    get_analytics.assert_not_awaited()


@pytest.mark.parametrize(
    "conversation",
    [
        {"conversation_id": "c1", "user_id": "owner", "visibility": "private"},
        {"conversation_id": "c1", "user_id": "other", "visibility": "public"},
    ],
    ids=["owner-private", "authenticated-public"],
)
def test_conversation_analytics_allows_readable_conversation(
    monkeypatch,
    conversation,
):
    get_conversation = AsyncMock(return_value=conversation)
    get_analytics = AsyncMock(return_value=_analytics())
    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation_analytics",
        get_analytics,
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_analytics_app(current_user)) as client:
        response = client.get("/conversations/c1/analytics")

    assert response.status_code == 200
    assert response.json()["conversation_id"] == "c1"
    get_analytics.assert_awaited_once_with("c1", "session")


def test_user_conversation_routes_require_an_active_user():
    expected = {
        ("/users/{user_id}/conversations", "GET"),
        ("/users/{user_id}/conversations", "DELETE"),
        ("/users/{user_id}/message-count", "GET"),
        ("/users/{user_id}/statistics", "GET"),
    }

    for path, method in expected:
        names = {
            dependency.call.__name__
            for dependency in _route(path, method).dependant.dependencies
        }
        assert "get_current_active_user" in names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "service_name", "kwargs"),
    [
        (
            "list_user_conversations",
            "list_conversations",
            {"status": None, "limit": 50, "offset": 0, "include_archived": False},
        ),
        ("delete_all_user_conversations", "delete_user_conversations", {}),
        ("get_user_message_count", "get_user_message_count", {"hours": 24}),
        ("get_user_statistics", "get_user_statistics", {}),
    ],
)
async def test_user_conversation_routes_hide_other_users(
    monkeypatch,
    handler_name,
    service_name,
    kwargs,
):
    service = AsyncMock()
    monkeypatch.setattr(chat_handlers.ChatService, service_name, service)
    handler = getattr(chat_handlers, handler_name)

    with pytest.raises(HTTPException) as exc_info:
        await handler(
            user_id="other-user",
            current_user=SimpleNamespace(user_id="owner", is_active=True),
            **kwargs,
        )

    assert exc_info.value.status_code == 404
    service.assert_not_awaited()
