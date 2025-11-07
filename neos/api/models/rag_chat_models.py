"""RAG Chat API Models"""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

# 기존 chat_models에서 import
from neos.api.models.chat_models import MessageRole, SendMessageRequest


# ============================================================================
# RAG-specific Request Models
# ============================================================================

class RAGSendMessageRequest(SendMessageRequest):
    """RAG 기반 메시지 전송 요청"""
    enable_rag: bool = Field(default=True, description="RAG 활성화 여부")
    rag_top_k: int = Field(default=3, ge=1, le=10, description="유사 메시지 검색 수")
    include_cross_conversation: bool = Field(
        default=False,
        description="다른 대화에서도 검색할지 여부"
    )


class SimilaritySearchRequest(BaseModel):
    """유사도 검색 요청"""
    query: str = Field(..., min_length=1, description="검색 쿼리")
    strategy: str = Field(
        default="conversation",
        pattern="^(conversation|cross_conversation|hybrid)$",
        description="검색 전략"
    )
    limit: int = Field(default=10, ge=1, le=50, description="검색 결과 수")
    similarity_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="유사도 임계값"
    )


class CreateEmbeddingRequest(BaseModel):
    """임베딩 생성 요청"""
    message_id: str = Field(..., description="메시지 ID")
    force_recreate: bool = Field(default=False, description="기존 임베딩 덮어쓰기")


# ============================================================================
# Response Models
# ============================================================================

class SimilarMessageResult(BaseModel):
    """유사 메시지 검색 결과"""
    message_id: str
    conversation_id: str
    content: str
    role: str
    similarity_score: float
    sequence_number: Optional[int] = None
    conversation_title: Optional[str] = None
    created_at: Optional[str] = None
    search_type: str


class SimilaritySearchResponse(BaseModel):
    """유사도 검색 응답"""
    success: bool
    query: str
    strategy: str
    results: List[SimilarMessageResult]
    total_results: int


class RAGContextInfo(BaseModel):
    """RAG 컨텍스트 정보"""
    relevant_messages_count: int
    relevant_messages: List[Dict[str, Any]]


class RAGMessageResponse(BaseModel):
    """RAG 기반 메시지 응답"""
    success: bool
    user_message_id: str
    assistant_message_id: str
    assistant_content: str
    rag_enabled: bool
    rag_context: Optional[RAGContextInfo] = None
    usage: Dict[str, int]
    cost_usd: float
    latency_ms: int


class EmbeddingStatsResponse(BaseModel):
    """임베딩 통계 응답"""
    total_embeddings: int
    conversations_count: int
    first_embedding_at: Optional[str] = None
    last_embedding_at: Optional[str] = None


class CreateEmbeddingResponse(BaseModel):
    """임베딩 생성 응답"""
    success: bool
    message_id: str
    message: str
