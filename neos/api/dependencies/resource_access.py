from typing import Any

from fastapi import Depends, HTTPException, status

from neos.api.dependencies.auth import get_current_active_user
from neos.api.services.chat_service import ChatService
from neos.database.models import Document, User
from neos.workflow.stream_manager import StreamSession


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found",
    )


async def _get_document_by_id(document_id: int) -> Document | None:
    from neos.api.services.document_service import DocumentService

    return await DocumentService.get_document_by_id(document_id)


async def get_owned_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    conversation = await ChatService.get_conversation(conversation_id)
    if not conversation or conversation.get("user_id") != current_user.user_id:
        raise _not_found()
    return conversation


async def get_readable_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    conversation = await ChatService.get_conversation(conversation_id)
    if not conversation:
        raise _not_found()
    is_owner = conversation.get("user_id") == current_user.user_id
    is_public = conversation.get("visibility") == "public"
    if not (is_owner or is_public):
        raise _not_found()
    return conversation


async def get_owned_message(
    message_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    message = await ChatService.get_message(message_id)
    if not message:
        raise _not_found()
    conversation = await ChatService.get_conversation(message["conversation_id"])
    if not conversation or conversation.get("user_id") != current_user.user_id:
        raise _not_found()
    return message


async def get_owned_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
) -> Document:
    document = await _get_document_by_id(document_id)
    if not document or document.user_id != current_user.user_id:
        raise _not_found()
    return document


def require_same_user_id(requested_user_id: str, current_user: User) -> None:
    if requested_user_id != current_user.user_id:
        raise _not_found()


def require_stream_session_owner(session: StreamSession, current_user: User) -> None:
    if not session.user_id or session.user_id != current_user.user_id:
        raise _not_found()
