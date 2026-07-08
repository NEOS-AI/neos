from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import chat_handlers
from neos.api.models.chat_models import CreateConversationRequest, EditMessageRequest
from neos.api.services.chat_service import ChatService
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


def _message(
    *,
    conversation_id: str = "c1",
    message_id: str = "m1",
    parent_message_id: str | None = None,
) -> dict:
    return {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "role": "user",
        "content": "updated",
        "sequence_number": 1,
        "parent_message_id": parent_message_id,
        "status": "edited",
        "created_at": "2026-07-01T00:00:00",
        "updated_at": "2026-07-01T00:00:00",
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


def _chat_app(current_user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_handlers.router)

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
    return app


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs", "service_attr"),
    [
        (
            "POST",
            "/templates",
            {
                "json": {
                    "name": "starter",
                    "created_by": "attacker",
                    "description": "template",
                    "category": "general",
                    "default_model": "claude-sonnet-4-5-20250929",
                    "default_system_prompt": "hello",
                    "default_temperature": 0.7,
                    "default_settings": {},
                    "initial_messages": [],
                    "is_public": False,
                    "tags": [],
                    "metadata": {},
                }
            },
            "create_template",
        ),
        ("GET", "/templates/t1", {}, "get_template"),
        ("GET", "/templates", {}, "list_templates"),
    ],
)
def test_template_routes_reject_unauthenticated_before_services(
    monkeypatch,
    method,
    path,
    request_kwargs,
    service_attr,
):
    service = AsyncMock()
    monkeypatch.setattr(ChatService, service_attr, service)

    with TestClient(_chat_app()) as client:
        response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401
    service.assert_not_awaited()


def test_create_template_uses_authenticated_identity(monkeypatch):
    create_template = AsyncMock(
        return_value={
            "template_id": "t1",
            "name": "starter",
            "description": "template",
            "category": "general",
            "default_model": "claude-sonnet-4-5-20250929",
            "default_system_prompt": "hello",
            "default_temperature": 0.7,
            "default_settings": {},
            "initial_messages": [],
            "is_public": False,
            "is_active": True,
            "created_by": "owner",
            "usage_count": 0,
            "created_at": "2026-07-01T00:00:00",
            "updated_at": "2026-07-01T00:00:00",
            "tags": [],
            "metadata": {},
        }
    )
    monkeypatch.setattr(ChatService, "create_template", create_template)

    with TestClient(_chat_app(current_user=SimpleNamespace(user_id="owner", is_active=True))) as client:
        response = client.post(
            "/templates",
            json={
                "name": "starter",
                "created_by": "attacker",
                "description": "template",
                "category": "general",
                "default_model": "claude-sonnet-4-5-20250929",
                "default_system_prompt": "hello",
                "default_temperature": 0.7,
                "default_settings": {},
                "initial_messages": [],
                "is_public": False,
                "tags": [],
                "metadata": {},
            },
        )

    assert response.status_code == 200
    assert create_template.await_args.kwargs["created_by"] == "owner"


class _FakeRoutePipeline:
    def __init__(self):
        self.calls = []

    async def run(
        self,
        conversation_id,
        request,
        current_user,
        *,
        authorized_conversation,
    ):
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "parent_message_id": request.parent_message_id,
                "user_id": current_user.user_id,
                "authorized_conversation": authorized_conversation,
            }
        )
        yield "data: [DONE]\n\n"


async def _completed_llm_stream(**kwargs):
    yield {"type": "content", "content": "allowed response"}
    yield {
        "type": "complete",
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
        "cost": {"total_cost": 0},
        "latency_ms": 1,
    }


def _configure_parent_route_services(
    monkeypatch,
    *,
    parent_message,
    parent_conversation,
):
    target_conversation = {
        "conversation_id": "owned-c",
        "user_id": "owner",
        "visibility": "private",
        "system_prompt": "",
        "model_name": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": None,
    }
    conversations = {"owned-c": target_conversation}
    if parent_conversation is not None:
        conversations[parent_conversation["conversation_id"]] = parent_conversation

    get_conversation = AsyncMock(
        side_effect=lambda conversation_id: conversations.get(conversation_id)
    )
    get_message = AsyncMock(return_value=parent_message)
    add_message = AsyncMock(
        return_value=_message(
            conversation_id="owned-c",
            message_id="created-m",
            parent_message_id=(parent_message or {}).get("message_id"),
        )
    )
    get_conversation_messages = AsyncMock(return_value=[])
    pipeline = _FakeRoutePipeline()
    pipeline_factory = Mock(return_value=pipeline)

    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(chat_handlers.ChatService, "get_message", get_message)
    monkeypatch.setattr(chat_handlers.ChatService, "add_message", add_message)
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "get_conversation_messages",
        get_conversation_messages,
    )
    monkeypatch.setattr(chat_handlers, "_get_chat_stream_pipeline", pipeline_factory)
    monkeypatch.setattr(
        chat_handlers.chat_llm_service,
        "generate_response_stream_with_tools",
        _completed_llm_stream,
    )
    monkeypatch.setattr(
        chat_handlers.cost_calculator,
        "record_cost_for_existing_message",
        AsyncMock(),
    )
    monkeypatch.setattr(chat_handlers.app_settings, "ENABLE_WORKFLOW_IN_CHAT", False)
    monkeypatch.setattr(chat_handlers.app_settings, "ARTIFACTS_ENABLED", False)
    monkeypatch.setattr(chat_handlers.app_settings, "INLINE_VIS_ENABLED", False)
    monkeypatch.setattr(chat_handlers.app_settings, "TOOL_SEARCH_ENABLED", False)

    return add_message, get_message, pipeline, pipeline_factory


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


def test_message_routes_declare_access_dependencies():
    expected = {
        ("/conversations/{conversation_id}/messages", "POST"): "get_owned_conversation",
        ("/conversations/{conversation_id}/messages", "GET"): "get_readable_conversation",
        ("/messages/{message_id}", "GET"): "get_owned_message",
        ("/messages/{message_id}", "PATCH"): "get_owned_message",
        ("/messages/{message_id}/feedback", "POST"): "get_owned_message",
        ("/messages/{message_id}", "DELETE"): "get_owned_message",
        ("/messages/{message_id}/regenerate", "POST"): "get_owned_message",
        ("/conversations/{conversation_id}/messages/stream", "POST"): "get_owned_conversation",
        ("/conversations/{conversation_id}/messages/stream_legacy", "POST"): "get_owned_conversation",
    }

    for (path, method), dependency_name in expected.items():
        names = {
            dependency.call.__name__
            for dependency in _route(path, method).dependant.dependencies
        }
        assert dependency_name in names


def test_send_message_rejects_unauthenticated_before_service(monkeypatch):
    get_conversation = AsyncMock(return_value=_conversation())
    add_message = AsyncMock()
    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(chat_handlers.ChatService, "add_message", add_message)

    with TestClient(_chat_app()) as client:
        response = client.post(
            "/conversations/c1/messages",
            json={"content": "secret"},
        )

    assert response.status_code == 401
    get_conversation.assert_not_awaited()
    add_message.assert_not_awaited()


@pytest.mark.parametrize(
    "conversation",
    [
        {"conversation_id": "c1", "user_id": "other", "visibility": "public"},
        None,
    ],
    ids=["non-owner-public", "missing"],
)
def test_send_message_hides_non_owner_and_missing_before_write(
    monkeypatch,
    conversation,
):
    get_conversation = AsyncMock(return_value=conversation)
    add_message = AsyncMock()
    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(chat_handlers.ChatService, "add_message", add_message)
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_chat_app(current_user)) as client:
        response = client.post(
            "/conversations/c1/messages",
            json={"content": "secret"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    add_message.assert_not_awaited()


@pytest.mark.parametrize(
    "conversation",
    [
        {"conversation_id": "c1", "user_id": "other", "visibility": "public"},
        None,
    ],
    ids=["non-owner-public", "missing"],
)
def test_stream_message_hides_non_owner_and_missing_before_pipeline(
    monkeypatch,
    conversation,
):
    get_conversation = AsyncMock(return_value=conversation)
    pipeline_factory = AsyncMock()
    monkeypatch.setattr(chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(chat_handlers, "_get_chat_stream_pipeline", pipeline_factory)
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_chat_app(current_user)) as client:
        response = client.post(
            "/conversations/c1/messages/stream",
            json={"content": "secret"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    pipeline_factory.assert_not_called()


@pytest.mark.parametrize(
    ("route_suffix", "uses_pipeline"),
    [
        ("messages", False),
        ("messages/stream", True),
        ("messages/stream_legacy", False),
    ],
    ids=["ordinary", "current-stream", "legacy-stream"],
)
@pytest.mark.parametrize(
    ("parent_message_id", "parent_message", "parent_conversation"),
    [
        (
            "victim-m",
            {"message_id": "victim-m", "conversation_id": "victim-c"},
            {
                "conversation_id": "victim-c",
                "user_id": "victim",
                "visibility": "private",
            },
        ),
        (
            "other-owned-m",
            {"message_id": "other-owned-m", "conversation_id": "other-owned-c"},
            {
                "conversation_id": "other-owned-c",
                "user_id": "owner",
                "visibility": "private",
            },
        ),
        ("missing-m", None, None),
    ],
    ids=["cross-owner", "same-owner-cross-conversation", "missing"],
)
def test_message_creation_routes_hide_invalid_parent_before_write(
    monkeypatch,
    route_suffix,
    uses_pipeline,
    parent_message_id,
    parent_message,
    parent_conversation,
):
    add_message, _, pipeline, pipeline_factory = _configure_parent_route_services(
        monkeypatch,
        parent_message=parent_message,
        parent_conversation=parent_conversation,
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_chat_app(current_user)) as client:
        response = client.post(
            f"/conversations/owned-c/{route_suffix}",
            json={
                "content": "secret",
                "role": "assistant",
                "parent_message_id": parent_message_id,
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    assert response.headers["content-type"].startswith("application/json")
    assert "response.failed" not in response.text
    add_message.assert_not_awaited()
    assert pipeline.calls == []
    if uses_pipeline:
        pipeline_factory.assert_not_called()


@pytest.mark.parametrize(
    "route_suffix",
    ["messages", "messages/stream", "messages/stream_legacy"],
    ids=["ordinary", "current-stream", "legacy-stream"],
)
@pytest.mark.parametrize(
    "parent_message_id",
    ["same-conversation-m", None],
    ids=["same-conversation", "no-parent"],
)
def test_message_creation_routes_preserve_valid_parent_success(
    monkeypatch,
    route_suffix,
    parent_message_id,
):
    parent_message = (
        {
            "message_id": "same-conversation-m",
            "conversation_id": "owned-c",
        }
        if parent_message_id
        else None
    )
    parent_conversation = (
        {
            "conversation_id": "owned-c",
            "user_id": "owner",
            "visibility": "private",
        }
        if parent_message_id
        else None
    )
    add_message, get_message, pipeline, pipeline_factory = (
        _configure_parent_route_services(
            monkeypatch,
            parent_message=parent_message,
            parent_conversation=parent_conversation,
        )
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_chat_app(current_user)) as client:
        response = client.post(
            f"/conversations/owned-c/{route_suffix}",
            json={
                "content": "allowed",
                "role": "assistant",
                "parent_message_id": parent_message_id,
            },
        )

    assert response.status_code == 200
    if parent_message_id is None:
        get_message.assert_not_awaited()
    if route_suffix == "messages/stream":
        pipeline_factory.assert_called_once_with()
        assert pipeline.calls[0]["parent_message_id"] == parent_message_id
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text == "data: [DONE]\n\n"
    else:
        assert add_message.await_args_list[0].kwargs["parent_message_id"] == parent_message_id
        if route_suffix == "messages/stream_legacy":
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "response.completed" in response.text
            assert "response.failed" not in response.text
            assert response.text.endswith("data: [DONE]\n\n")


def test_edit_message_request_accepts_omitted_deprecated_user_id():
    request = EditMessageRequest(new_content="updated")

    assert request.user_id is None


@pytest.mark.asyncio
async def test_edit_message_uses_authenticated_user(monkeypatch):
    edited_message = AsyncMock(return_value=_message())
    monkeypatch.setattr(chat_handlers.ChatService, "edit_message", edited_message)
    request = EditMessageRequest(new_content="updated", user_id="attacker")

    await chat_handlers.edit_message(
        message_id="m1",
        request=request,
        current_user=SimpleNamespace(user_id="owner", is_active=True),
        _message={"message_id": "m1", "conversation_id": "c1"},
    )

    assert edited_message.await_args.kwargs["edited_by"] == "owner"


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
        ("/templates", "POST"),
        ("/templates", "GET"),
        ("/templates/{template_id}", "GET"),
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
