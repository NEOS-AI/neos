from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from neos.api.dependencies import resource_access


@pytest.fixture
def owner():
    return SimpleNamespace(user_id="user-a", is_active=True)


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
async def test_owned_conversation_hides_cross_user_resource(monkeypatch, owner):
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
        await resource_access.get_owned_conversation("c1", owner)
    assert exc.value.status_code == 404


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
async def test_owned_message_checks_parent_conversation(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_message",
        AsyncMock(return_value={"message_id": "m1", "conversation_id": "c1"}),
    )
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
        await resource_access.get_owned_message("m1", owner)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_owned_document_checks_document_user(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.DocumentService,
        "get_document_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7, user_id="user-b")),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_document(7, owner)
    assert exc.value.status_code == 404


def test_same_user_path_and_stream_session_are_scoped(owner):
    resource_access.require_same_user_id("user-a", owner)
    resource_access.require_stream_session_owner(
        SimpleNamespace(user_id="user-a"), owner
    )
    with pytest.raises(HTTPException):
        resource_access.require_same_user_id("user-b", owner)
    with pytest.raises(HTTPException):
        resource_access.require_stream_session_owner(
            SimpleNamespace(user_id="user-b"), owner
        )
