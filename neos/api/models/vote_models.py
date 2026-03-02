"""Vote & Feedback API Pydantic Models"""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class VoteRequest(BaseModel):
    """투표 생성/업데이트 요청"""
    chat_id: str = Field(..., description="Chat ID (conversation_id)")
    message_id: str = Field(..., description="Message ID")
    is_upvoted: bool = Field(..., description="Is upvoted (true) or downvoted (false)")

    class Config:
        json_schema_extra = {
            "example": {
                "chat_id": "conv_abc123",
                "message_id": "msg_xyz789",
                "is_upvoted": True
            }
        }


class VoteResponse(BaseModel):
    """투표 응답"""
    chat_id: str
    message_id: str
    is_upvoted: bool

    class Config:
        json_schema_extra = {
            "example": {
                "chat_id": "conv_abc123",
                "message_id": "msg_xyz789",
                "is_upvoted": True
            }
        }


# ── Phase 2.11: Feedback System ──────────────────────────────────────

class FeedbackRequest(BaseModel):
    """피드백 요청 (투표 + 텍스트 피드백)"""
    chat_id: str = Field(..., description="Chat ID")
    message_id: str = Field(..., description="Message ID")
    is_upvoted: bool = Field(..., description="Upvote (true) or downvote (false)")
    feedback_text: Optional[str] = Field(None, max_length=2000, description="Optional text feedback")
    feedback_category: Optional[str] = Field(
        None,
        description="Feedback category: source_quality, incorrect_info, prompt_issue, missing_info, other"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "chat_id": "conv_abc123",
                "message_id": "msg_xyz789",
                "is_upvoted": False,
                "feedback_text": "The sources cited were outdated",
                "feedback_category": "source_quality"
            }
        }


class FeedbackResponse(BaseModel):
    """피드백 응답"""
    chat_id: str
    message_id: str
    is_upvoted: bool
    feedback_text: Optional[str] = None
    feedback_category: Optional[str] = None


class FeedbackAggregation(BaseModel):
    """피드백 집계 결과"""
    total_votes: int = 0
    upvotes: int = 0
    downvotes: int = 0
    feedback_count: int = 0
    category_counts: Dict[str, int] = Field(default_factory=dict)
    upvote_rate: float = 0.0
