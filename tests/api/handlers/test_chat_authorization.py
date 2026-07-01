from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from neos.api.handlers import chat_handlers
from neos.api.models.chat_models import CreateConversationRequest


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
    }

    for (path, method), dependency_name in expected.items():
        names = {
            dependency.call.__name__
            for dependency in _route(path, method).dependant.dependencies
        }
        assert dependency_name in names


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
