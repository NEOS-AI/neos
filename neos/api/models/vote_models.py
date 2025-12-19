"""Vote API Pydantic Models"""

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
