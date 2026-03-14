from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Float, ForeignKey, ARRAY, Boolean, Index, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from pgvector.sqlalchemy import Vector
import uuid

from .connection import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), unique=True, nullable=False, index=True)

    # 인증 정보
    email = Column(String(255), unique=True, nullable=True, index=True)  # nullable for backward compatibility
    username = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)  # bcrypt hash

    # 계정 상태
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)

    # 역할 및 권한
    role = Column(String(50), default="user")  # user, admin, premium, etc.

    # OAuth 지원
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    profile_picture_url = Column(String(1000), nullable=True)

    # 이메일 검증
    email_verified_at = Column(TIMESTAMP, nullable=True)

    # 조직 관계 (엔터프라이즈)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)

    # 개인 구독 (Organization 없는 경우)
    subscription_tier = Column(String(50), default="free")  # free, pro, enterprise
    subscription_status = Column(String(50), default="active")
    subscription_start_date = Column(TIMESTAMP, nullable=True)
    subscription_end_date = Column(TIMESTAMP, nullable=True)

    # 개인 사용량 (Organization 없는 경우)
    usage_quota = Column(JSONB, default=dict)  # {"queries_per_day": 100}
    usage_current = Column(JSONB, default=dict)  # {"queries_today": 5}

    # 결제 정보
    billing_customer_id = Column(String(255), nullable=True)  # Stripe Customer ID

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(TIMESTAMP, nullable=True)

    # 사용자 설정
    preferences = Column(JSONB, default=dict)

    # 관계
    query_histories = relationship("QueryHistory", back_populates="user")
    search_sessions = relationship("SearchSession", back_populates="user")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    oauth_accounts = relationship("UserOAuthAccount", back_populates="user", cascade="all, delete-orphan")
    organization = relationship("Organization", back_populates="members")

class QueryHistory(Base):
    __tablename__ = "query_history"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), ForeignKey("users.user_id"))
    original_query = Column(Text, nullable=False)
    processed_query = Column(Text)
    query_vector = Column(Vector(1536))  # OpenAI embedding 차원
    query_intent = Column(String(100))
    search_results = Column(JSONB)
    response_quality_score = Column(Float, default=0.0)
    execution_time_ms = Column(Integer)
    tools_used = Column(ARRAY(String))
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # 관계
    user = relationship("User", back_populates="query_histories")
    source_relations = relationship("RelatedQuery", foreign_keys="[RelatedQuery.source_query_id]")
    related_relations = relationship("RelatedQuery", foreign_keys="[RelatedQuery.related_query_id]")


class RelatedQuery(Base):
    __tablename__ = "related_queries"
    
    id = Column(Integer, primary_key=True)
    source_query_id = Column(Integer, ForeignKey("query_history.id"))
    related_query_id = Column(Integer, ForeignKey("query_history.id"))
    similarity_score = Column(Float)
    relation_type = Column(String(50))  # 'semantic', 'sequential', 'collaborative'
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

class TrendingQuery(Base):
    __tablename__ = "trending_queries"
    
    id = Column(Integer, primary_key=True)
    query_text = Column(Text, nullable=False)
    query_vector = Column(Vector(1536))
    search_count = Column(Integer, default=1)
    last_searched = Column(TIMESTAMP, default=datetime.utcnow)
    time_period = Column(String(20))  # 'hourly', 'daily', 'weekly'
    category = Column(String(100))


class SearchSession(Base):
    __tablename__ = "search_sessions"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(255), nullable=False)
    user_id = Column(String(255), ForeignKey("users.user_id"))
    query_sequence = Column(JSONB)  # 쿼리 순서와 시간 정보
    session_intent = Column(String(100))
    total_queries = Column(Integer, default=0)
    session_duration_ms = Column(Integer)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    ended_at = Column(TIMESTAMP)

    # 관계
    user = relationship("User", back_populates="search_sessions")


# ============================================================================
# Document Management Models
# ============================================================================

class Document(Base):
    """문서 메타데이터 및 원본 파일 정보"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)

    # 파일 정보
    filename = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_size = Column(Integer)  # bytes
    mime_type = Column(String(100))
    file_hash = Column(String(64))  # SHA-256 해시

    # S3/Storage 정보
    storage_provider = Column(String(50), default="s3")  # 's3', 'rustfs', 'local'
    storage_bucket = Column(String(255))
    storage_key = Column(String(1000), nullable=False)
    storage_url = Column(String(2000))

    # 문서 메타데이터
    title = Column(String(500))
    author = Column(String(255))
    language = Column(String(10))
    page_count = Column(Integer)
    word_count = Column(Integer)

    # 처리 상태
    processing_status = Column(String(50), default="pending")  # 'pending', 'processing', 'completed', 'failed'
    processing_error = Column(Text)

    # 지식 그래프 처리 여부
    kg_extracted = Column(Boolean, default=False)
    kg_extraction_date = Column(TIMESTAMP)

    # 임베딩 처리 여부
    embedding_processed = Column(Boolean, default=False)
    embedding_date = Column(TIMESTAMP)

    # FTS 인덱싱 여부
    fts_indexed = Column(Boolean, default=False)
    fts_index_date = Column(TIMESTAMP)

    # 추가 메타데이터
    extra_metadata = Column(JSONB, default=dict)

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    user = relationship("User")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    knowledge_graph = relationship("KnowledgeGraph", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """문서 청크 (임베딩 및 FTS용)"""
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    # 청크 정보
    chunk_index = Column(Integer, nullable=False)  # 문서 내 청크 순서
    chunk_text = Column(Text, nullable=False)
    contextual_text = Column(Text, nullable=True)   # Contextual Retrieval: context_snippet + "\n\n" + chunk_text
    chunk_size = Column(Integer)  # 문자 수

    # 위치 정보
    page_number = Column(Integer)
    start_offset = Column(Integer)
    end_offset = Column(Integer)

    # 임베딩
    embedding = Column(Vector(1536))  # OpenAI embedding

    # Parent-child 청킹
    parent_chunk_id = Column(Integer, ForeignKey("document_chunks.id"), nullable=True)
    chunking_strategy = Column(String(20), default="sentence")  # fixed, sentence, semantic, parent_child

    # 청크 메타데이터
    chunk_type = Column(String(50))  # 'paragraph', 'heading', 'list', 'table', 'code'
    heading_hierarchy = Column(ARRAY(String))  # 상위 헤딩 정보

    # FTS를 위한 ts_vector는 PostgreSQL에서 자동 생성되도록 설정
    # (별도 마이그레이션에서 처리)

    # 추가 메타데이터
    extra_metadata = Column(JSONB, default=dict)

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    # 관계
    document = relationship("Document", back_populates="chunks")


class KnowledgeGraph(Base):
    """지식 그래프 엔티티 및 관계"""
    __tablename__ = "knowledge_graphs"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    # 엔티티 정보
    entity_id = Column(String(255), nullable=False)  # 문서 내 고유 ID
    entity_type = Column(String(100), nullable=False)  # 'person', 'organization', 'concept', 'event', etc.
    entity_name = Column(String(500), nullable=False)
    entity_description = Column(Text)

    # 임베딩
    entity_embedding = Column(Vector(1536))

    # 관계 정보 (JSON 배열로 저장)
    relations = Column(JSONB, default=list)  # [{"target_entity_id": "...", "relation_type": "...", "confidence": 0.9}]

    # 엔티티 속성
    properties = Column(JSONB, default=dict)  # {"role": "CEO", "founded": "2020", ...}

    # 출현 위치 (문서 내)
    occurrences = Column(JSONB, default=list)  # [{"chunk_id": 1, "page": 3, "context": "..."}]

    # 신뢰도 및 중요도
    confidence_score = Column(Float, default=0.0)
    importance_score = Column(Float, default=0.0)

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    document = relationship("Document", back_populates="knowledge_graph")


# ============================================================================
# Authentication & Authorization Models
# ============================================================================

class APIKey(Base):
    """API 키 관리"""
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)

    # 키 정보
    name = Column(String(255), nullable=False)  # 사용자가 지정하는 키 이름 (예: "Production API", "Testing")
    key_hash = Column(String(255), nullable=False, unique=True)  # SHA-256 해시
    key_prefix = Column(String(20), nullable=False)  # 표시용 prefix (예: "neos_abc...")

    # 권한 및 제한
    scopes = Column(ARRAY(String), default=list)  # 권한 범위 (예: ["query:read", "chat:write"])
    rate_limit = Column(Integer, default=100)  # 분당 요청 수
    max_requests_per_day = Column(Integer, nullable=True)  # 일일 최대 요청 수 (None = 무제한)

    # 사용 통계
    total_requests = Column(Integer, default=0)
    last_used_at = Column(TIMESTAMP, nullable=True)
    last_used_ip = Column(String(45), nullable=True)  # IPv6 지원

    # 상태 및 만료
    is_active = Column(Boolean, default=True)
    expires_at = Column(TIMESTAMP, nullable=True)  # None = 만료 없음

    # 메타데이터
    description = Column(Text, nullable=True)
    key_metadata = Column(JSONB, default=dict)

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    user = relationship("User", back_populates="api_keys")

    # 인덱스
    __table_args__ = (
        Index("idx_api_keys_user_id", "user_id"),
        Index("idx_api_keys_key_hash", "key_hash"),
        Index("idx_api_keys_is_active", "is_active"),
    )


class RefreshToken(Base):
    """리프레시 토큰 관리 (토큰 rotation 지원)"""
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)

    # 토큰 정보
    token_hash = Column(String(255), nullable=False, unique=True)  # SHA-256 해시

    # 세션 정보
    session_id = Column(String(255), nullable=True)  # BFF 세션 ID (optional)
    device_info = Column(String(500), nullable=True)  # User-Agent 정보
    ip_address = Column(String(45), nullable=True)  # IPv6 지원

    # 상태
    is_revoked = Column(Boolean, default=False)
    is_used = Column(Boolean, default=False)  # 1회용 토큰 (rotation)

    # 만료
    expires_at = Column(TIMESTAMP, nullable=False)

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    used_at = Column(TIMESTAMP, nullable=True)
    revoked_at = Column(TIMESTAMP, nullable=True)

    # 관계
    user = relationship("User", back_populates="refresh_tokens")

    # 인덱스
    __table_args__ = (
        Index("idx_refresh_tokens_user_id", "user_id"),
        Index("idx_refresh_tokens_token_hash", "token_hash"),
        Index("idx_refresh_tokens_expires_at", "expires_at"),
    )


class UserOAuthAccount(Base):
    """OAuth Provider와 사용자 계정 연결"""
    __tablename__ = "user_oauth_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)

    # OAuth Provider 정보
    provider = Column(String(50), nullable=False)  # 'google', 'github', 'microsoft'
    provider_account_id = Column(String(255), nullable=False)  # Google sub
    provider_account_email = Column(String(255), nullable=True)

    # 프로필 정보 스냅샷
    profile_data = Column(JSONB, default=dict)  # {name, picture, email, locale}

    # 연결 정보
    linked_at = Column(TIMESTAMP, default=datetime.utcnow)
    last_used_at = Column(TIMESTAMP, nullable=True)

    # 관계
    user = relationship("User", back_populates="oauth_accounts")

    # 제약조건 및 인덱스
    __table_args__ = (
        Index("idx_oauth_user_id", "user_id"),
        Index("idx_oauth_provider", "provider", "provider_account_id"),
    )


class Organization(Base):
    """회사/조직 (엔터프라이즈 기능)"""
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 조직 정보
    name = Column(String(255), nullable=False)
    domain = Column(String(255), unique=True, nullable=False, index=True)  # company.com
    logo_url = Column(String(1000), nullable=True)

    # 구독 정보 (조직 레벨)
    subscription_tier = Column(String(50), default="enterprise")
    subscription_status = Column(String(50), default="active")
    subscription_start_date = Column(TIMESTAMP, nullable=True)
    subscription_end_date = Column(TIMESTAMP, nullable=True)

    # 사용량 풀링 (조직 전체)
    usage_quota = Column(JSONB, default=dict)  # {"queries_per_month": 10000}
    usage_current = Column(JSONB, default=dict)  # {"queries_this_month": 523}

    # 결제 정보
    billing_customer_id = Column(String(255), nullable=True)
    billing_email = Column(String(255), nullable=True)

    # 설정
    auto_join_enabled = Column(Boolean, default=False)  # 도메인 이메일 자동 가입
    require_approval = Column(Boolean, default=True)  # 관리자 승인 필요

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    members = relationship("User", back_populates="organization")
    admins = relationship("OrganizationAdmin", back_populates="organization", cascade="all, delete-orphan")

    # 인덱스
    __table_args__ = (
        Index("idx_organizations_domain", "domain"),
    )


class OrganizationAdmin(Base):
    """조직 관리자"""
    __tablename__ = "organization_admins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id = Column(String(255), ForeignKey("users.user_id", ondelete="CASCADE"))

    role = Column(String(50), default="admin")  # admin, owner
    granted_at = Column(TIMESTAMP, default=datetime.utcnow)

    # 관계
    organization = relationship("Organization", back_populates="admins")

    # 제약조건
    __table_args__ = (
        Index("idx_org_admins_organization_id", "organization_id"),
        Index("idx_org_admins_user_id", "user_id"),
    )


# ============================================================================
# Smart Cache Models (pgvector 기반)
# ============================================================================

class QueryCacheEntry(Base):
    """
    스마트 캐시 엔트리 - pgvector 기반 의미론적 캐싱

    쿼리 유형별 동적 TTL과 의미 기반 유사 쿼리 캐싱을 지원합니다.
    """
    __tablename__ = "query_cache"

    id = Column(Integer, primary_key=True)

    # 쿼리 정보
    query_text = Column(Text, nullable=False)
    query_hash = Column(String(64), nullable=False, index=True)  # SHA-256 해시
    query_vector = Column(Vector(1536))  # OpenAI embedding 차원

    # 분류 정보 (동적 TTL 계산에 사용)
    query_intent = Column(String(50), nullable=False, index=True)  # 쿼리 의도
    complexity_score = Column(Float, default=0.0)  # 복잡도 점수 (0.0~1.0)

    # 캐시된 응답
    response_data = Column(JSONB, nullable=False)  # 캐시된 전체 응답
    response_quality_score = Column(Float, default=0.0)  # 응답 품질 점수 (0.0~1.0)

    # TTL 관리
    ttl_seconds = Column(Integer, nullable=False)  # 계산된 TTL (초)
    expires_at = Column(TIMESTAMP, nullable=False, index=True)  # 만료 시간

    # 사용 통계
    hit_count = Column(Integer, default=0)  # 캐시 히트 횟수
    last_accessed_at = Column(TIMESTAMP, nullable=True)  # 마지막 접근 시간

    # 멀티테넌시 (선택적)
    user_id = Column(String(255), nullable=True, index=True)  # 사용자별 캐시
    session_id = Column(String(255), nullable=True)  # 세션별 캐시

    # 추가 메타데이터
    cache_metadata = Column(JSONB, default=dict)  # 추가 메타데이터

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 인덱스
    __table_args__ = (
        Index("idx_query_cache_expires_at", "expires_at"),
        Index("idx_query_cache_intent", "query_intent"),
        Index("idx_query_cache_hash", "query_hash"),
        Index("idx_query_cache_user_id", "user_id"),
        # pgvector IVFFlat 인덱스는 마이그레이션 SQL에서 별도 생성
    )


class CacheStatistics(Base):
    """
    캐시 통계 - 캐시 성능 모니터링용

    시간대별, 쿼리 유형별 캐시 히트율 및 성능 지표 추적
    """
    __tablename__ = "cache_statistics"

    id = Column(Integer, primary_key=True)

    # 시간 구간
    time_bucket = Column(TIMESTAMP, nullable=False, index=True)  # 1시간 단위

    # 쿼리 유형
    query_intent = Column(String(50), nullable=False, index=True)

    # 통계 데이터
    total_requests = Column(Integer, default=0)  # 총 요청 수
    cache_hits = Column(Integer, default=0)  # 캐시 히트 수
    cache_misses = Column(Integer, default=0)  # 캐시 미스 수
    semantic_hits = Column(Integer, default=0)  # 의미 기반 히트 수
    exact_hits = Column(Integer, default=0)  # 정확 매칭 히트 수

    # 성능 지표
    avg_similarity_score = Column(Float, default=0.0)  # 평균 유사도 점수
    avg_response_time_ms = Column(Integer, default=0)  # 평균 응답 시간
    avg_ttl_remaining = Column(Integer, default=0)  # 평균 남은 TTL

    # 저장 현황
    total_cached_entries = Column(Integer, default=0)  # 총 캐시 엔트리 수
    storage_size_bytes = Column(Integer, default=0)  # 저장 용량 (바이트)

    # 타임스탬프
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 인덱스
    __table_args__ = (
        Index("idx_cache_stats_time_bucket", "time_bucket"),
        Index("idx_cache_stats_intent", "query_intent"),
        # 복합 인덱스: 시간대 + 쿼리 유형
        Index("idx_cache_stats_time_intent", "time_bucket", "query_intent"),
    )


# ============================================================================
# Web Frontend Models (Vote, Artifact Document, Suggestion)
# ============================================================================

class Vote(Base):
    """
    메시지 투표 - 웹 프론트엔드 피드백 시스템

    사용자가 AI 응답에 대해 upvote 또는 downvote를 할 수 있습니다.
    """
    __tablename__ = "Vote_v2"

    # 프론트엔드 DB는 camelCase를 사용하므로 매핑 필요
    chat_id = Column("chatId", UUID(as_uuid=True), primary_key=True, nullable=False)
    message_id = Column("messageId", UUID(as_uuid=True), primary_key=True, nullable=False)
    is_upvoted = Column("isUpvoted", Boolean, nullable=False)

    # Phase 2.11: Feedback columns (migration 013)
    feedback_text = Column("feedback_text", Text, nullable=True)
    feedback_category = Column("feedback_category", String(50), nullable=True)

    # 관계 설정은 Conversation, Message 모델이 있어야 가능
    # conversation = relationship("Conversation")
    # message = relationship("Message")


class ArtifactDocument(Base):
    """
    Artifact 문서 - 웹 프론트엔드에서 생성되는 코드, 문서, 스프레드시트 등

    id와 created_at의 복합 primary key로 버전 관리를 지원합니다.
    """
    __tablename__ = "Document"

    # 프론트엔드 DB는 camelCase를 사용하므로 매핑 필요
    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False)
    created_at = Column("createdAt", TIMESTAMP, primary_key=True, nullable=False, default=datetime.utcnow)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    kind = Column(String(20), nullable=False, default="text")  # text, code, image, sheet
    user_id = Column("userId", String(255), nullable=False)  # 백엔드 User.user_id (String)와 일치하도록 변경

    # 관계 설정은 프론트엔드 DB 구조와 맞지 않아 비활성화
    # user = relationship("User")
    # suggestions = relationship("Suggestion", back_populates="document", cascade="all, delete-orphan")


class Suggestion(Base):
    """
    문서 편집 제안 - AI가 생성한 문서 개선 제안

    Document와 연결되어 original_text를 suggested_text로 바꾸는 제안을 저장합니다.
    """
    __tablename__ = "Suggestion"

    # 프론트엔드 DB는 camelCase를 사용하므로 매핑 필요
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    document_id = Column("documentId", UUID(as_uuid=True), nullable=False)
    document_created_at = Column("documentCreatedAt", TIMESTAMP, nullable=False)
    original_text = Column("originalText", Text, nullable=False)
    suggested_text = Column("suggestedText", Text, nullable=False)
    description = Column(Text, nullable=True)
    is_resolved = Column("isResolved", Boolean, nullable=False, default=False)
    user_id = Column("userId", String(255), nullable=False)  # 백엔드 User.user_id (String)와 일치하도록 변경
    created_at = Column("createdAt", TIMESTAMP, nullable=False, default=datetime.utcnow)

    # 복합 외래키는 유지 (Document 테이블 참조)
    __table_args__ = (
        ForeignKeyConstraint(
            ['documentId', 'documentCreatedAt'],
            ['Document.id', 'Document.createdAt']
        ),
    )

    # 관계 설정은 프론트엔드 DB 구조와 맞지 않아 비활성화
    # user = relationship("User")
    # document = relationship("ArtifactDocument", back_populates="suggestions")


class ToolRegistry(Base):
    """도구 레지스트리 - Advanced Tool Search를 위한 도구 메타데이터 저장소"""
    __tablename__ = "tool_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255))
    description = Column(Text, nullable=False)
    schema = Column(JSONB)                              # Anthropic tool input_schema
    category = Column(String(100))                      # search, analysis, document, data, general
    tags = Column(ARRAY(Text))                          # 검색 보조 태그
    source_type = Column(String(50), nullable=False)    # skill, mcp_tool, artifact_tool, custom
    defer_loading = Column(Boolean, default=True)       # False=코어 도구, True=검색 대상
    is_active = Column(Boolean, default=True)

    # 검색 인덱스
    embedding = Column(Vector(1536))                    # 도구 설명 임베딩 (pgvector)
    # search_vector는 DB에서 GENERATED ALWAYS AS ... STORED로 자동 생성 (읽기 전용)

    # 메타데이터
    usage_count = Column(Integer, default=0)
    last_used_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
