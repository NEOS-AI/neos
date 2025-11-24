"""Chat API Pydantic models"""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    FUNCTION = "function"
    TOOL = "tool"


class MessageStatus(str, Enum):
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EDITED = "edited"


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ChatMode(str, Enum):
    STANDARD = "standard"
    RAG = "rag"
    SIMILARITY = "similarity"
    DEEP_RESEARCH = "deep_research"


# ============================================================================
# Request Models
# ============================================================================

class CreateConversationRequest(BaseModel):
    user_id: str = Field(..., description="사용자 ID")
    title: Optional[str] = Field(None, max_length=500, description="대화 제목")
    model_name: str = Field(default="claude-opus-4-1-20250805", description="사용할 모델")
    system_prompt: Optional[str] = Field(None, description="시스템 프롬프트")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Temperature 설정")
    max_tokens: Optional[int] = Field(None, gt=0, description="최대 토큰 수")
    mode: ChatMode = Field(default=ChatMode.STANDARD, description="대화 모드 (standard, rag, similarity, deep_research)")
    template_id: Optional[str] = Field(None, description="템플릿 ID (선택)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500, description="대화 제목")
    system_prompt: Optional[str] = Field(None, description="시스템 프롬프트")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature")
    is_pinned: Optional[bool] = Field(None, description="고정 여부")
    tags: Optional[List[str]] = Field(None, description="태그 목록")
    metadata: Optional[Dict[str, Any]] = Field(None, description="메타데이터")


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, description="메시지 내용")
    role: MessageRole = Field(default=MessageRole.USER, description="메시지 역할")
    parent_message_id: Optional[str] = Field(None, description="부모 메시지 ID (브랜치용)")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="첨부파일")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class SendSimilarityMessageRequest(BaseModel):
    """유사도 검색 기반 채팅 메시지 요청"""
    content: str = Field(..., min_length=1, description="메시지 내용")
    role: MessageRole = Field(default=MessageRole.USER, description="메시지 역할")
    parent_message_id: Optional[str] = Field(None, description="부모 메시지 ID")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="첨부파일")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")

    # 유사도 검색 설정
    top_k: int = Field(default=3, ge=1, le=10, description="검색할 유사 메시지 수")
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="유사도 임계값")
    include_cross_conversation: bool = Field(default=False, description="다른 대화에서도 검색")
    enable_auto_embedding: bool = Field(default=True, description="자동 임베딩 생성")
    time_range_days: Optional[int] = Field(None, ge=1, le=365, description="검색 시간 범위 (일 단위, None=전체)")


class RegenerateMessageRequest(BaseModel):
    message_id: str = Field(..., description="재생성할 메시지 ID")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature")
    model_name: Optional[str] = Field(None, description="사용할 모델")


class EditMessageRequest(BaseModel):
    new_content: str = Field(..., min_length=1, description="새 메시지 내용")
    edit_reason: Optional[str] = Field(None, description="편집 이유")
    user_id: str = Field(default="system", description="편집자 ID")


class MessageFeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(positive|negative|neutral)$", description="피드백")
    comment: Optional[str] = Field(None, description="피드백 코멘트")


# ============================================================================
# Response Models
# ============================================================================

class MessageAttachment(BaseModel):
    type: str
    url: Optional[str] = None
    name: Optional[str] = None
    size: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: Optional[Dict[str, Any]] = None


class MessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    role: MessageRole
    content: str
    content_type: str = "text"
    sequence_number: int
    parent_message_id: Optional[str] = None
    status: MessageStatus

    # AI 메타데이터
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    finish_reason: Optional[str] = None

    # 도구 사용
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)

    # 첨부파일
    attachments: List[MessageAttachment] = Field(default_factory=list)

    # 피드백
    user_feedback: Optional[str] = None
    feedback_comment: Optional[str] = None
    quality_score: Optional[float] = None

    # 타임스탬프
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationResponse(BaseModel):
    conversation_id: str
    user_id: str
    title: Optional[str] = None
    summary: Optional[str] = None

    # 모델 설정
    model_name: str
    model_version: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: float
    max_tokens: Optional[int] = None
    mode: str = "standard"

    # 상태
    status: ConversationStatus
    is_pinned: bool = False
    is_shared: bool = False
    share_token: Optional[str] = None

    # 통계
    message_count: int = 0
    total_tokens_used: int = 0
    total_cost: float = 0.0

    # 타임스탬프
    last_message_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # 메타데이터
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationWithMessagesResponse(BaseModel):
    conversation: ConversationResponse
    messages: List[MessageResponse]
    participant_count: int = 1
    has_more_messages: bool = False


class ConversationSummary(BaseModel):
    conversation_id: str
    user_id: str
    title: Optional[str] = None
    model_name: str
    status: ConversationStatus
    is_pinned: bool = False
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: datetime
    first_message_preview: Optional[str] = None
    last_message_preview: Optional[str] = None


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]
    total_count: int
    has_more: bool


class ChatStreamChunk(BaseModel):
    """스트리밍 응답 청크"""
    type: str  # 'start', 'content', 'tool_call', 'complete', 'error'
    content: Optional[str] = None
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateMessageResponse(BaseModel):
    success: bool
    user_message: MessageResponse
    assistant_message: Optional[MessageResponse] = None
    conversation_id: str
    errors: List[str] = Field(default_factory=list)


class SimilarityMessageMetadata(BaseModel):
    """유사도 검색 메타데이터"""
    message_id: str
    similarity_score: float
    search_type: str  # "conversation" or "cross_conversation"


class CreateSimilarityMessageResponse(BaseModel):
    """유사도 검색 기반 채팅 응답"""
    success: bool
    user_message: MessageResponse
    assistant_message: Optional[MessageResponse] = None
    conversation_id: str
    errors: List[str] = Field(default_factory=list)

    # 유사도 검색 메타데이터
    context_enhanced: bool = False
    relevant_message_count: int = 0
    similarity_scores: List[SimilarityMessageMetadata] = Field(default_factory=list)
    search_config: Dict[str, Any] = Field(default_factory=dict)


class SuccessResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============================================================================
# Analytics Models
# ============================================================================

class ConversationAnalytics(BaseModel):
    conversation_id: str
    analysis_period: str
    period_start: datetime
    period_end: datetime

    # 사용 통계
    total_messages: int = 0
    user_messages: int = 0
    assistant_messages: int = 0

    # 토큰 사용량
    total_tokens_used: int = 0
    prompt_tokens_used: int = 0
    completion_tokens_used: int = 0
    estimated_cost: float = 0.0

    # 품질 메트릭
    average_response_time_ms: Optional[int] = None
    average_message_length: Optional[int] = None
    average_quality_score: Optional[float] = None

    # 도구 사용
    tools_used: List[Dict[str, Any]] = Field(default_factory=list)
    tool_call_count: int = 0

    # 사용자 활동
    positive_feedback_count: int = 0
    negative_feedback_count: int = 0
    messages_edited_count: int = 0


class UserChatStatistics(BaseModel):
    user_id: str
    total_conversations: int
    active_conversations: int
    pinned_conversations: int
    total_messages: int
    total_tokens: int
    total_cost: float
    last_activity_at: Optional[datetime] = None
    first_conversation_at: Optional[datetime] = None


# ============================================================================
# Template Models
# ============================================================================

class ConversationTemplate(BaseModel):
    template_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None

    default_model: str
    default_system_prompt: Optional[str] = None
    default_temperature: float = 0.7
    default_settings: Dict[str, Any] = Field(default_factory=dict)

    initial_messages: List[Dict[str, Any]] = Field(default_factory=list)

    is_public: bool = False
    is_active: bool = True
    created_by: str
    usage_count: int = 0

    created_at: datetime
    updated_at: datetime

    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)

    default_model: str = Field(default="claude-opus-4-1-20250805")
    default_system_prompt: Optional[str] = None
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    default_settings: Dict[str, Any] = Field(default_factory=dict)

    initial_messages: List[Dict[str, Any]] = Field(default_factory=list)

    is_public: bool = Field(default=False)
    created_by: str = Field(default="system", description="템플릿 생성자 ID")
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TemplateListResponse(BaseModel):
    templates: List[ConversationTemplate]
    total_count: int
