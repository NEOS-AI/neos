"""RAG chat router 인증 고정 테스트.

이 파일의 라우트 7개는 인증 의존성이 전혀 없었다 (지뢰 -- 마운트되면 즉시
악용 가능). 형제인 similarity_chat_handlers.py와 동일하게
`get_owned_conversation` / `get_owned_message` / `require_same_user_id` +
`get_current_active_user`를 걸어야 한다.

`test_chat_authorization.py`가 하던 대로, 개수가 아니라 **경로 이름으로**
검증한다 -- 카운트는 누가 빠졌는지 말해주지 않는다.
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import rag_chat_handlers


def _user(user_id: str = "owner"):
    return SimpleNamespace(user_id=user_id, is_active=True)


def _conversation(*, conversation_id: str = "c1", user_id: str = "owner"):
    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "visibility": "private",
        "system_prompt": "",
        "model_name": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": None,
    }


def _message(*, message_id: str = "m1", conversation_id: str = "c1"):
    return {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "role": "user",
        "content": "hi",
        "sequence_number": 1,
    }


def _route(path: str, method: str) -> APIRoute:
    routes = [
        route for route in rag_chat_handlers.router.routes if isinstance(route, APIRoute)
    ]
    return next(route for route in routes if route.path == path and method in route.methods)


def _app(current_user=None):
    app = FastAPI()
    app.include_router(rag_chat_handlers.router)
    if current_user is None:
        async def unauthenticated():
            raise HTTPException(status_code=401, detail="Authentication required")

        app.dependency_overrides[get_current_active_user] = unauthenticated
    else:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
    return app


# ============================================================================
# 1) 경로별 의존성 이름 고정 -- 브리프의 매핑 표 그대로
# ============================================================================

CONVERSATION_GATED_ROUTES = {
    ("/conversations/{conversation_id}/messages/rag", "POST"): "get_owned_conversation",
    ("/conversations/{conversation_id}/messages/rag/stream", "POST"): "get_owned_conversation",
    ("/conversations/{conversation_id}/search", "POST"): "get_owned_conversation",
}

MESSAGE_GATED_ROUTES = {
    ("/messages/{message_id}/embedding", "POST"): "get_owned_message",
    ("/messages/{message_id}/embedding", "DELETE"): "get_owned_message",
}

USER_SCOPED_ROUTES = {
    ("/users/{user_id}/search", "POST"),
    ("/users/{user_id}/embeddings/stats", "GET"),
}


@pytest.mark.parametrize(("path", "method"), CONVERSATION_GATED_ROUTES.keys())
def test_conversation_routes_declare_get_owned_conversation(path, method):
    names = {
        dependency.call.__name__ for dependency in _route(path, method).dependant.dependencies
    }
    assert CONVERSATION_GATED_ROUTES[(path, method)] in names, (
        f"{method} {path} is missing get_owned_conversation -- found {names}"
    )


@pytest.mark.parametrize(("path", "method"), MESSAGE_GATED_ROUTES.keys())
def test_message_routes_declare_get_owned_message(path, method):
    names = {
        dependency.call.__name__ for dependency in _route(path, method).dependant.dependencies
    }
    assert MESSAGE_GATED_ROUTES[(path, method)] in names, (
        f"{method} {path} is missing get_owned_message -- found {names}"
    )


@pytest.mark.parametrize(("path", "method"), USER_SCOPED_ROUTES)
def test_user_scoped_routes_require_an_active_user(path, method):
    """require_same_user_id는 함수 안에서 호출되므로 Depends 목록에 나타나지
    않는다 -- 최소한 인증된 사용자를 요구하는지는 여기서 고정하고, 본인 확인
    자체는 아래 test_user_scoped_routes_hide_other_users 에서 고정한다."""
    names = {
        dependency.call.__name__ for dependency in _route(path, method).dependant.dependencies
    }
    assert "get_current_active_user" in names, (
        f"{method} {path} is missing get_current_active_user -- found {names}"
    )


# ============================================================================
# 2) 인증 없이는 서비스 호출 전에 거부된다
# ============================================================================

@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/conversations/c1/messages/rag", {"content": "hi"}),
        ("POST", "/conversations/c1/messages/rag/stream", {"content": "hi"}),
        ("POST", "/conversations/c1/search", {"query": "hi"}),
        ("POST", "/users/u1/search", {"query": "hi"}),
        ("POST", "/messages/m1/embedding", {"message_id": "m1"}),
        ("GET", "/users/u1/embeddings/stats", None),
        ("DELETE", "/messages/m1/embedding", None),
    ],
)
def test_all_seven_routes_reject_unauthenticated_before_services(
    monkeypatch, method, path, json_body
):
    get_conversation = AsyncMock()
    get_message = AsyncMock()
    search = AsyncMock()
    create_embedding = AsyncMock()
    delete_embedding = AsyncMock()
    get_stats = AsyncMock()
    monkeypatch.setattr(rag_chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(rag_chat_handlers.ChatService, "get_message", get_message)
    monkeypatch.setattr(
        rag_chat_handlers.similarity_search_service, "search", search
    )
    monkeypatch.setattr(
        rag_chat_handlers.message_embedding_service,
        "create_message_embedding",
        create_embedding,
    )
    monkeypatch.setattr(
        rag_chat_handlers.message_embedding_service,
        "delete_message_embedding",
        delete_embedding,
    )
    monkeypatch.setattr(
        rag_chat_handlers.message_embedding_service,
        "get_user_embeddings_stats",
        get_stats,
    )

    with TestClient(_app()) as client:
        response = client.request(method, path, json=json_body)

    assert response.status_code == 401
    get_conversation.assert_not_awaited()
    get_message.assert_not_awaited()
    search.assert_not_awaited()
    create_embedding.assert_not_awaited()
    delete_embedding.assert_not_awaited()
    get_stats.assert_not_awaited()


# ============================================================================
# 3) 대화 소유자가 아니면 (또는 대화가 없으면) 404, 서비스는 호출되지 않는다
# ============================================================================

@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/conversations/c1/messages/rag", {"content": "hi"}),
        ("POST", "/conversations/c1/messages/rag/stream", {"content": "hi"}),
        ("POST", "/conversations/c1/search", {"query": "hi"}),
    ],
)
@pytest.mark.parametrize(
    "conversation",
    [None, _conversation(user_id="other")],
    ids=["missing", "foreign-owner"],
)
def test_conversation_gated_routes_hide_foreign_and_missing(
    monkeypatch, method, path, json_body, conversation
):
    get_conversation = AsyncMock(return_value=conversation)
    search = AsyncMock()
    monkeypatch.setattr(rag_chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(rag_chat_handlers.similarity_search_service, "search", search)

    with TestClient(_app(_user())) as client:
        response = client.request(method, path, json=json_body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    search.assert_not_awaited()


# ============================================================================
# 4) 메시지 소유자가 아니면 (또는 메시지가 없으면) 404, 서비스는 호출되지 않는다
# ============================================================================

@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/messages/m1/embedding", {"message_id": "m1"}),
        ("DELETE", "/messages/m1/embedding", None),
    ],
)
@pytest.mark.parametrize(
    ("message", "conversation"),
    [
        (None, None),
        (_message(conversation_id="c1"), _conversation(conversation_id="c1", user_id="other")),
    ],
    ids=["missing", "foreign-owner"],
)
def test_message_gated_routes_hide_foreign_and_missing(
    monkeypatch, method, path, json_body, message, conversation
):
    get_message = AsyncMock(return_value=message)
    get_conversation = AsyncMock(return_value=conversation)
    create_embedding = AsyncMock()
    delete_embedding = AsyncMock()
    monkeypatch.setattr(rag_chat_handlers.ChatService, "get_message", get_message)
    monkeypatch.setattr(rag_chat_handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(
        rag_chat_handlers.message_embedding_service,
        "create_message_embedding",
        create_embedding,
    )
    monkeypatch.setattr(
        rag_chat_handlers.message_embedding_service,
        "delete_message_embedding",
        delete_embedding,
    )

    with TestClient(_app(_user())) as client:
        response = client.request(method, path, json=json_body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    create_embedding.assert_not_awaited()
    delete_embedding.assert_not_awaited()


# ============================================================================
# 5) require_same_user_id: 남의 user_id로는 접근할 수 없다
# ============================================================================

@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/users/other-user/search", {"query": "hi"}),
        ("GET", "/users/other-user/embeddings/stats", None),
    ],
)
def test_user_scoped_routes_hide_other_users(monkeypatch, method, path, json_body):
    search = AsyncMock()
    get_stats = AsyncMock()
    monkeypatch.setattr(rag_chat_handlers.similarity_search_service, "search", search)
    monkeypatch.setattr(
        rag_chat_handlers.message_embedding_service, "get_user_embeddings_stats", get_stats
    )

    with TestClient(_app(_user("owner"))) as client:
        response = client.request(method, path, json=json_body)

    assert response.status_code == 404
    search.assert_not_awaited()
    get_stats.assert_not_awaited()
