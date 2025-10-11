"""웹 검색 로그 데이터 타입 정의"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class SearchEngineType(str, Enum):
    """검색 엔진 타입"""
    WEB = "web"
    ACADEMIC = "academic"
    NEWS = "news"
    DATA = "data"
    VIDEO = "video"
    IMAGE = "image"
    CUSTOM = "custom"


class SearchQueryStatus(str, Enum):
    """검색 쿼리 상태"""
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CACHED = "cached"
    PENDING = "pending"


class ContentType(str, Enum):
    """콘텐츠 타입"""
    ARTICLE = "article"
    PRODUCT = "product"
    NEWS = "news"
    ACADEMIC = "academic"
    VIDEO = "video"
    IMAGE = "image"
    FORUM = "forum"
    DOCUMENTATION = "documentation"
    BLOG = "blog"
    OTHER = "other"


class ResultChangeType(str, Enum):
    """결과 변경 타입"""
    CONTENT_UPDATE = "content_update"
    TITLE_CHANGE = "title_change"
    METADATA_UPDATE = "metadata_update"
    REMOVED = "removed"


class RelationType(str, Enum):
    """결과 간 관계 타입"""
    DUPLICATE = "duplicate"
    SIMILAR = "similar"
    RELATED = "related"
    UPDATED_VERSION = "updated_version"


# ============================================================================
# Base Models
# ============================================================================

class SearchEngineBase(BaseModel):
    """검색 엔진 기본 정보"""
    engine_name: str = Field(..., description="검색 엔진 이름")
    engine_type: SearchEngineType = Field(..., description="검색 엔진 타입")
    engine_version: Optional[str] = Field(None, description="엔진 버전")
    base_url: Optional[str] = Field(None, description="기본 URL")
    rate_limit_per_minute: Optional[int] = Field(None, description="분당 요청 제한")
    max_results_per_query: Optional[int] = Field(None, description="쿼리당 최대 결과 수")
    supports_async: bool = Field(True, description="비동기 지원 여부")
    configuration: Dict[str, Any] = Field(default_factory=dict, description="엔진 설정")
    capabilities: Dict[str, Any] = Field(default_factory=dict, description="엔진 기능")
    is_active: bool = Field(True, description="활성화 상태")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")

    class Config:
        from_attributes = True


class SearchEngineCreate(SearchEngineBase):
    """검색 엔진 생성 모델"""
    pass


class SearchEngineUpdate(BaseModel):
    """검색 엔진 업데이트 모델"""
    engine_type: Optional[SearchEngineType] = None
    engine_version: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit_per_minute: Optional[int] = None
    max_results_per_query: Optional[int] = None
    supports_async: Optional[bool] = None
    configuration: Optional[Dict[str, Any]] = None
    capabilities: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_deprecated: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class SearchEngineResponse(SearchEngineBase):
    """검색 엔진 응답 모델"""
    id: int
    total_queries_executed: int = Field(0, description="실행된 총 쿼리 수")
    total_results_returned: int = Field(0, description="반환된 총 결과 수")
    average_response_time_ms: Optional[int] = Field(None, description="평균 응답 시간 (ms)")
    success_rate: float = Field(1.0, description="성공률")
    is_deprecated: bool = Field(False, description="폐기 여부")
    created_at: datetime
    updated_at: datetime
    deprecated_at: Optional[datetime] = None


# ============================================================================
# Search Query Models
# ============================================================================

class WebSearchQueryBase(BaseModel):
    """웹 검색 쿼리 기본 정보"""
    query_text: str = Field(..., description="검색 쿼리 텍스트")
    query_language: Optional[str] = Field(None, description="쿼리 언어 (ko, en, ja 등)")
    query_intent: Optional[str] = Field(None, description="쿼리 의도")
    engine_name: str = Field(..., description="검색 엔진 이름")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    search_params: Dict[str, Any] = Field(default_factory=dict, description="검색 파라미터")
    trace_id: Optional[str] = Field(None, description="분산 추적 ID")
    parent_query_id: Optional[str] = Field(None, description="부모 쿼리 ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")

    class Config:
        from_attributes = True


class WebSearchQueryCreate(WebSearchQueryBase):
    """웹 검색 쿼리 생성 모델"""
    query_id: str = Field(..., description="쿼리 고유 ID (UUID)")
    query_hash: str = Field(..., description="쿼리 해시값")
    engine_id: int = Field(..., description="검색 엔진 ID")


class WebSearchQueryUpdate(BaseModel):
    """웹 검색 쿼리 업데이트 모델"""
    execution_time_ms: Optional[int] = None
    timeout_occurred: Optional[bool] = None
    total_results_count: Optional[int] = None
    results_returned_count: Optional[int] = None
    status: Optional[SearchQueryStatus] = None
    error_message: Optional[str] = None
    quality_score: Optional[float] = None
    was_cached: Optional[bool] = None
    cache_hit_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class WebSearchQueryResponse(WebSearchQueryBase):
    """웹 검색 쿼리 응답 모델"""
    id: int
    query_id: str
    query_hash: str
    engine_id: int
    executed_at: datetime
    execution_time_ms: Optional[int] = None
    timeout_occurred: bool = False
    total_results_count: int = 0
    results_returned_count: int = 0
    status: SearchQueryStatus = SearchQueryStatus.COMPLETED
    error_message: Optional[str] = None
    quality_score: Optional[float] = None
    was_cached: bool = False
    cache_hit_at: Optional[datetime] = None


# ============================================================================
# Search Result Models
# ============================================================================

class WebSearchResultBase(BaseModel):
    """웹 검색 결과 기본 정보"""
    result_url: str = Field(..., description="결과 URL")
    result_position: Optional[int] = Field(None, description="검색 결과 순위")
    result_title: Optional[str] = Field(None, description="결과 제목")
    result_content: Optional[str] = Field(None, description="결과 내용")
    result_summary: Optional[str] = Field(None, description="결과 요약")
    author: Optional[str] = Field(None, description="작성자")
    published_date: Optional[datetime] = Field(None, description="발행일")
    last_modified_date: Optional[datetime] = Field(None, description="최종 수정일")
    domain: Optional[str] = Field(None, description="도메인")
    relevance_score: Optional[float] = Field(None, description="관련성 점수")
    quality_score: Optional[float] = Field(None, description="품질 점수")
    confidence_score: Optional[float] = Field(None, description="신뢰도 점수")
    content_type: Optional[ContentType] = Field(None, description="콘텐츠 타입")
    content_category: Optional[str] = Field(None, description="콘텐츠 카테고리")
    structured_data: Dict[str, Any] = Field(default_factory=dict, description="구조화된 데이터")
    extracted_entities: List[Any] = Field(default_factory=list, description="추출된 엔티티")
    extracted_keywords: List[str] = Field(default_factory=list, description="추출된 키워드")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")

    class Config:
        from_attributes = True


class WebSearchResultCreate(WebSearchResultBase):
    """웹 검색 결과 생성 모델"""
    result_id: str = Field(..., description="결과 고유 ID (UUID)")
    query_id: str = Field(..., description="쿼리 ID")
    url_hash: str = Field(..., description="URL 해시값")
    content_hash: Optional[str] = Field(None, description="콘텐츠 해시값")


class WebSearchResultUpdate(BaseModel):
    """웹 검색 결과 업데이트 모델"""
    result_title: Optional[str] = None
    result_content: Optional[str] = None
    result_summary: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    last_modified_date: Optional[datetime] = None
    relevance_score: Optional[float] = None
    quality_score: Optional[float] = None
    confidence_score: Optional[float] = None
    content_type: Optional[ContentType] = None
    content_category: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    extracted_entities: Optional[List[Any]] = None
    extracted_keywords: Optional[List[str]] = None
    content_hash: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class WebSearchResultResponse(WebSearchResultBase):
    """웹 검색 결과 응답 모델"""
    id: int
    result_id: str
    query_id: str
    url_hash: str
    result_version: int = 1
    is_latest_version: bool = True
    content_hash: Optional[str] = None
    first_seen_at: datetime
    captured_at: datetime


# ============================================================================
# Metrics Models
# ============================================================================

class WebSearchMetricBase(BaseModel):
    """웹 검색 메트릭 기본 정보"""
    api_call_time_ms: Optional[int] = Field(None, description="API 호출 시간 (ms)")
    result_processing_time_ms: Optional[int] = Field(None, description="결과 처리 시간 (ms)")
    total_time_ms: Optional[int] = Field(None, description="총 소요 시간 (ms)")
    memory_used_mb: Optional[float] = Field(None, description="사용 메모리 (MB)")
    network_bytes_sent: Optional[int] = Field(None, description="전송된 네트워크 바이트")
    network_bytes_received: Optional[int] = Field(None, description="수신된 네트워크 바이트")
    results_relevance_avg: Optional[float] = Field(None, description="평균 관련성")
    results_diversity_score: Optional[float] = Field(None, description="결과 다양성 점수")
    user_satisfaction_score: Optional[float] = Field(None, description="사용자 만족도 점수")
    retry_count: int = Field(0, description="재시도 횟수")
    error_count: int = Field(0, description="에러 발생 횟수")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")

    class Config:
        from_attributes = True


class WebSearchMetricCreate(WebSearchMetricBase):
    """웹 검색 메트릭 생성 모델"""
    query_id: str = Field(..., description="쿼리 ID")


class WebSearchMetricResponse(WebSearchMetricBase):
    """웹 검색 메트릭 응답 모델"""
    id: int
    query_id: str
    recorded_at: datetime


# ============================================================================
# Aggregated Models
# ============================================================================

class SearchQueryWithResults(WebSearchQueryResponse):
    """검색 쿼리와 결과를 포함한 모델"""
    results: List[WebSearchResultResponse] = Field(default_factory=list, description="검색 결과 목록")
    metrics: Optional[WebSearchMetricResponse] = Field(None, description="검색 메트릭")


class SearchEnginePerformance(BaseModel):
    """검색 엔진 성능 요약"""
    id: int
    engine_name: str
    engine_type: str
    is_active: bool
    total_queries_executed: int
    total_results_returned: int
    success_rate: float
    avg_execution_time_ms: Optional[float]
    avg_quality_score: Optional[float]
    failed_queries_count: int
    successful_queries_count: int
    last_used_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# Search Log Request Models
# ============================================================================

class SearchLogRequest(BaseModel):
    """검색 로그 기록 요청 모델"""
    query_text: str = Field(..., description="검색 쿼리")
    engine_name: str = Field(..., description="검색 엔진 이름")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    query_language: Optional[str] = Field(None, description="쿼리 언어")
    query_intent: Optional[str] = Field(None, description="쿼리 의도")
    search_params: Dict[str, Any] = Field(default_factory=dict, description="검색 파라미터")
    trace_id: Optional[str] = Field(None, description="추적 ID")
    parent_query_id: Optional[str] = Field(None, description="부모 쿼리 ID")


class SearchResultItem(BaseModel):
    """개별 검색 결과 아이템"""
    url: str = Field(..., description="결과 URL")
    title: Optional[str] = Field(None, description="제목")
    content: Optional[str] = Field(None, description="내용/스니펫")
    score: Optional[float] = Field(None, description="관련성 점수")
    position: Optional[int] = Field(None, description="결과 순위")
    published_date: Optional[str] = Field(None, description="발행일 (ISO format)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class SearchLogComplete(BaseModel):
    """검색 완료 로그 모델"""
    query_id: str = Field(..., description="쿼리 ID")
    results: List[SearchResultItem] = Field(default_factory=list, description="검색 결과 목록")
    execution_time_ms: Optional[int] = Field(None, description="실행 시간 (ms)")
    status: SearchQueryStatus = Field(SearchQueryStatus.COMPLETED, description="검색 상태")
    error_message: Optional[str] = Field(None, description="에러 메시지")
    quality_score: Optional[float] = Field(None, description="품질 점수")
    metrics: Optional[Dict[str, Any]] = Field(None, description="성능 메트릭")
