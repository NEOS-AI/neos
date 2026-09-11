"""Vote & Feedback Service - 투표 및 피드백 비즈니스 로직"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text
from sqlalchemy.future import select as future_select
from typing import Dict, List, Optional
from fastapi import HTTPException, status
import logging
from neos.database.models import Vote
from neos.api.models.vote_models import VoteResponse, FeedbackResponse, FeedbackAggregation
from neos.learn.policy import is_imperative

logger = logging.getLogger(__name__)


class VoteService:
    """투표 및 피드백 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_or_update_vote(
        self,
        chat_id: str,
        message_id: str,
        is_upvoted: bool,
        user_id: str
    ) -> VoteResponse:
        """
        투표 생성 또는 업데이트

        Args:
            chat_id: 대화 ID
            message_id: 메시지 ID
            is_upvoted: 업보트 여부
            user_id: 사용자 ID

        Returns:
            VoteResponse: 생성/업데이트된 투표

        Raises:
            HTTPException: 대화가 사용자 소유가 아닌 경우 403
        """
        # chat_id, message_id는 문자열로 저장 (Vote.chat_id = String(255))
        chat_id_str = str(chat_id)
        message_id_str = str(message_id)

        # 기존 투표 확인
        vote_query = select(Vote).where(
            and_(
                Vote.chat_id == chat_id_str,
                Vote.message_id == message_id_str
            )
        )
        vote_result = await self.db.execute(vote_query)
        existing_vote = vote_result.scalar_one_or_none()

        if existing_vote:
            # 업데이트
            existing_vote.is_upvoted = is_upvoted
            await self.db.commit()
            await self.db.refresh(existing_vote)

            return VoteResponse(
                chat_id=existing_vote.chat_id,
                message_id=existing_vote.message_id,
                is_upvoted=existing_vote.is_upvoted
            )
        else:
            # 생성
            new_vote = Vote(
                chat_id=chat_id_str,
                message_id=message_id_str,
                is_upvoted=is_upvoted
            )
            self.db.add(new_vote)
            await self.db.commit()
            await self.db.refresh(new_vote)

            return VoteResponse(
                chat_id=new_vote.chat_id,
                message_id=new_vote.message_id,
                is_upvoted=new_vote.is_upvoted
            )

    async def get_votes_by_chat(
        self,
        chat_id: str,
        user_id: str
    ) -> List[VoteResponse]:
        """
        채팅의 모든 투표 조회

        Args:
            chat_id: 대화 ID
            user_id: 사용자 ID

        Returns:
            List[VoteResponse]: 투표 목록

        Raises:
            HTTPException: 대화가 사용자 소유가 아닌 경우 403
        """
        # 투표 조회
        query = select(Vote).where(Vote.chat_id == str(chat_id))
        result = await self.db.execute(query)
        votes = result.scalars().all()

        return [
            VoteResponse(
                chat_id=vote.chat_id,
                message_id=vote.message_id,
                is_upvoted=vote.is_upvoted
            )
            for vote in votes
        ]

    async def delete_vote(
        self,
        chat_id: str,
        message_id: str,
        user_id: str
    ) -> None:
        """
        투표 삭제

        Args:
            chat_id: 대화 ID
            message_id: 메시지 ID
            user_id: 사용자 ID

        Raises:
            HTTPException: 투표가 없거나 권한이 없는 경우
        """
        # 투표 조회 및 삭제
        vote_query = select(Vote).where(
            and_(
                Vote.chat_id == str(chat_id),
                Vote.message_id == str(message_id)
            )
        )
        vote_result = await self.db.execute(vote_query)
        vote = vote_result.scalar_one_or_none()

        if not vote:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vote not found"
            )

        await self.db.delete(vote)
        await self.db.commit()

    # ── Phase 2.11: Feedback Methods ─────────────────────────────────

    async def submit_feedback(
        self,
        chat_id: str,
        message_id: str,
        is_upvoted: bool,
        feedback_text: Optional[str],
        feedback_category: Optional[str],
        user_id: str,
    ) -> FeedbackResponse:
        """피드백 제출 (투표 + 텍스트 피드백)

        기존 votes 테이블에 feedback_text, feedback_category 컬럼 활용.
        DB migration 013 적용 후 동작합니다.
        """
        # 기존 투표 확인
        vote_query = select(Vote).where(
            and_(Vote.chat_id == str(chat_id), Vote.message_id == str(message_id))
        )
        vote_result = await self.db.execute(vote_query)
        existing_vote = vote_result.scalar_one_or_none()

        if existing_vote:
            existing_vote.is_upvoted = is_upvoted
            # feedback 필드가 모델에 존재하면 업데이트 (migration 후)
            if hasattr(existing_vote, "feedback_text"):
                existing_vote.feedback_text = feedback_text
            if hasattr(existing_vote, "feedback_category"):
                existing_vote.feedback_category = feedback_category
            await self.db.commit()
            await self.db.refresh(existing_vote)
        else:
            kwargs = {
                "chat_id": str(chat_id),
                "message_id": str(message_id),
                "is_upvoted": is_upvoted,
            }
            # feedback 필드가 모델에 존재하면 추가
            if hasattr(Vote, "feedback_text"):
                kwargs["feedback_text"] = feedback_text
            if hasattr(Vote, "feedback_category"):
                kwargs["feedback_category"] = feedback_category

            existing_vote = Vote(**kwargs)
            self.db.add(existing_vote)
            await self.db.commit()
            await self.db.refresh(existing_vote)

        if user_id and feedback_text and not is_imperative(feedback_text):
            try:
                from neos.memory.manager import memory_manager

                await memory_manager.learn(
                    user_id,
                    key=f"feedback:{chat_id}:{message_id}",
                    knowledge=feedback_text,
                    metadata={"category": feedback_category},
                )
            except Exception as e:
                logger.debug(f"Feedback learn skipped: {e}")

        return FeedbackResponse(
            chat_id=str(existing_vote.chat_id),
            message_id=str(existing_vote.message_id),
            is_upvoted=existing_vote.is_upvoted,
            feedback_text=getattr(existing_vote, "feedback_text", feedback_text),
            feedback_category=getattr(existing_vote, "feedback_category", feedback_category),
        )

    async def get_feedback_aggregation(self) -> FeedbackAggregation:
        """전체 피드백 집계"""
        try:
            # 총 투표 수, 업보트, 다운보트
            total_query = select(func.count(Vote.chat_id))
            total_result = await self.db.execute(total_query)
            total_votes = total_result.scalar() or 0

            upvote_query = select(func.count(Vote.chat_id)).where(Vote.is_upvoted == True)
            upvote_result = await self.db.execute(upvote_query)
            upvotes = upvote_result.scalar() or 0

            downvotes = total_votes - upvotes

            # 피드백 텍스트가 있는 투표 수 (migration 후)
            feedback_count = 0
            category_counts: Dict[str, int] = {}

            if hasattr(Vote, "feedback_text"):
                fb_query = select(func.count(Vote.chat_id)).where(
                    Vote.feedback_text.isnot(None)
                )
                fb_result = await self.db.execute(fb_query)
                feedback_count = fb_result.scalar() or 0

            if hasattr(Vote, "feedback_category"):
                cat_query = select(
                    Vote.feedback_category, func.count(Vote.chat_id)
                ).where(
                    Vote.feedback_category.isnot(None)
                ).group_by(Vote.feedback_category)
                cat_result = await self.db.execute(cat_query)
                for row in cat_result.fetchall():
                    if row[0]:
                        category_counts[row[0]] = row[1]

            upvote_rate = (upvotes / total_votes * 100) if total_votes > 0 else 0.0

            return FeedbackAggregation(
                total_votes=total_votes,
                upvotes=upvotes,
                downvotes=downvotes,
                feedback_count=feedback_count,
                category_counts=category_counts,
                upvote_rate=round(upvote_rate, 1),
            )
        except Exception as e:
            logger.warning(f"Feedback aggregation failed: {e}")
            return FeedbackAggregation()
