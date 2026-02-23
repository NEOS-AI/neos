"""Vote & Feedback API Handlers"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from neos.database.connection import get_db
from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.api.models.vote_models import (
    VoteRequest, VoteResponse,
    FeedbackRequest, FeedbackResponse, FeedbackAggregation,
)
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


# ── Phase 2.11: Feedback Endpoints ──────────────────────────────────

@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    feedback: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    피드백 제출 (투표 + 텍스트 피드백)

    - **is_upvoted**: thumbs up/down
    - **feedback_text**: 선택적 텍스트 피드백 (최대 2000자)
    - **feedback_category**: source_quality, incorrect_info, prompt_issue, missing_info, other
    """
    service = VoteService(db)
    return await service.submit_feedback(
        chat_id=feedback.chat_id,
        message_id=feedback.message_id,
        is_upvoted=feedback.is_upvoted,
        feedback_text=feedback.feedback_text,
        feedback_category=feedback.feedback_category,
        user_id=current_user.user_id,
    )


@router.get("/feedback/aggregation", response_model=FeedbackAggregation)
async def get_feedback_aggregation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    피드백 집계 조회

    Returns:
        전체 피드백 통계 (총 투표, 업보트율, 카테고리별 분포)
    """
    service = VoteService(db)
    return await service.get_feedback_aggregation()
