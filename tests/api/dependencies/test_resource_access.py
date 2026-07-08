import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies import resource_access
from neos.database.connection import get_db


@pytest.fixture
def owner():
    return SimpleNamespace(user_id="user-a", is_active=True)


def assert_resource_not_found(exc_info):
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Resource not found"


@pytest.mark.asyncio
async def test_owned_conversation_returns_owner_resource(monkeypatch, owner):
    conversation = {
        "conversation_id": "c1",
        "user_id": "user-a",
        "visibility": "private",
    }
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=conversation),
    )
    assert await resource_access.get_owned_conversation("c1", owner) == conversation


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["private", "public"])
async def test_owned_conversation_hides_cross_user_resource(
    monkeypatch, owner, visibility
):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(
            return_value={
                "conversation_id": "c1",
                "user_id": "user-b",
                "visibility": visibility,
            }
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_conversation("c1", owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
async def test_owned_conversation_hides_missing_resource(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=None),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_conversation("missing", owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
async def test_readable_conversation_allows_owner_private_read(monkeypatch, owner):
    conversation = {
        "conversation_id": "c1",
        "user_id": "user-a",
        "visibility": "private",
    }
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=conversation),
    )
    assert await resource_access.get_readable_conversation("c1", owner) == conversation


@pytest.mark.asyncio
async def test_readable_conversation_allows_authenticated_public_read(
    monkeypatch, owner
):
    conversation = {
        "conversation_id": "c1",
        "user_id": "user-b",
        "visibility": "public",
    }
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=conversation),
    )
    assert await resource_access.get_readable_conversation("c1", owner) == conversation


@pytest.mark.asyncio
async def test_readable_conversation_hides_cross_user_private_resource(
    monkeypatch, owner
):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(
            return_value={
                "conversation_id": "c1",
                "user_id": "user-b",
                "visibility": "private",
            }
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_readable_conversation("c1", owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
async def test_readable_conversation_hides_missing_resource(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=None),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_readable_conversation("missing", owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
async def test_owned_message_returns_message_for_conversation_owner(
    monkeypatch, owner
):
    message = {"message_id": "m1", "conversation_id": "c1"}
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_message",
        AsyncMock(return_value=message),
    )
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(
            return_value={
                "conversation_id": "c1",
                "user_id": "user-a",
                "visibility": "private",
            }
        ),
    )
    assert await resource_access.get_owned_message("m1", owner) == message


@pytest.mark.asyncio
async def test_owned_message_hides_missing_message(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_message",
        AsyncMock(return_value=None),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_message("missing", owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parent_conversation",
    [
        None,
        {"conversation_id": "c1", "user_id": "user-b", "visibility": "private"},
        {"conversation_id": "c1", "user_id": "user-b", "visibility": "public"},
    ],
    ids=["missing-parent", "private-non-owner", "public-non-owner"],
)
async def test_owned_message_hides_unowned_parent(
    monkeypatch, owner, parent_conversation
):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_message",
        AsyncMock(return_value={"message_id": "m1", "conversation_id": "c1"}),
    )
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=parent_conversation),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_message("m1", owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
async def test_owned_document_returns_owner_document(monkeypatch, owner):
    document = SimpleNamespace(id=7, user_id="user-a")
    monkeypatch.setattr(
        resource_access,
        "_get_document_by_id",
        AsyncMock(return_value=document),
    )
    assert await resource_access.get_owned_document(7, owner) == document


@pytest.mark.asyncio
async def test_owned_document_checks_document_user(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access,
        "_get_document_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7, user_id="user-b")),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_document(7, owner)
    assert_resource_not_found(exc)


@pytest.mark.asyncio
async def test_owned_document_hides_missing_document(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access,
        "_get_document_by_id",
        AsyncMock(return_value=None),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_document(404, owner)
    assert_resource_not_found(exc)


def test_same_user_path_allows_current_user(owner):
    resource_access.require_same_user_id("user-a", owner)


def test_same_user_path_hides_other_user(owner):
    with pytest.raises(HTTPException) as exc:
        resource_access.require_same_user_id("user-b", owner)
    assert_resource_not_found(exc)


def test_stream_session_allows_owner(owner):
    resource_access.require_stream_session_owner(
        SimpleNamespace(user_id="user-a"), owner
    )


@pytest.mark.parametrize("session_user_id", ["user-b", None])
def test_stream_session_hides_non_owner_and_unscoped_session(
    owner, session_user_id
):
    with pytest.raises(HTTPException) as exc:
        resource_access.require_stream_session_owner(
            SimpleNamespace(user_id=session_user_id), owner
        )
    assert_resource_not_found(exc)


def test_public_conversation_read_requires_authentication(monkeypatch):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(
            return_value={
                "conversation_id": "c1",
                "user_id": "user-b",
                "visibility": "public",
            }
        ),
    )

    app = FastAPI()

    @app.get("/conversations/{conversation_id}")
    async def read_conversation(
        conversation=Depends(resource_access.get_readable_conversation),
    ):
        return conversation

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        response = client.get("/conversations/c1")

    assert response.status_code == 401
