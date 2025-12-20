"""Vote API Handlers"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from neos.database.connection import get_db
from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.api.models.vote_models import VoteRequest, VoteResponse
from neos.api.services.vote_service import VoteService


router = APIRouter(prefix="/votes", tags=["votes"])


@router.post("", response_model=VoteResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_vote(
    vote_data: VoteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    메시지에 투표 생성/업데이트

    - **chat_id**: 대화 ID
    - **message_id**: 메시지 ID
    - **is_upvoted**: 업보트(true) 또는 다운보트(false)

    투표가 이미 존재하면 업데이트하고, 없으면 새로 생성합니다.
    """
    service = VoteService(db)
    return await service.create_or_update_vote(
        chat_id=vote_data.chat_id,
        message_id=vote_data.message_id,
        is_upvoted=vote_data.is_upvoted,
        user_id=current_user.user_id
    )


@router.get("/{chat_id}", response_model=List[VoteResponse])
async def get_votes_by_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    채팅의 모든 투표 조회

    - **chat_id**: 대화 ID

    Returns:
        해당 대화의 모든 투표 목록
    """
    service = VoteService(db)
    return await service.get_votes_by_chat(chat_id, current_user.user_id)


@router.delete("/{chat_id}/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vote(
    chat_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    투표 삭제

    - **chat_id**: 대화 ID
    - **message_id**: 메시지 ID
    """
    service = VoteService(db)
    await service.delete_vote(chat_id, message_id, current_user.user_id)
    return None
