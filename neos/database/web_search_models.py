"""웹 검색 로그 데이터베이스 모델"""

from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Float, Boolean, BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from .connection import Base


class SearchEngine(Base):
    """검색 엔진 정보 및 설정"""
    __tablename__ = "search_engines"

    id = Column(Integer, primary_key=True)
    engine_name = Column(String(100), unique=True, nullable=False)
    engine_type = Column(String(50), nullable=False)
    engine_version = Column(String(50))
    base_url = Column(Text)
    rate_limit_per_minute = Column(Integer)
    max_results_per_query = Column(Integer)
    supports_async = Column(Boolean, default=True)

    # 엔진 설정 및 메타데이터
    configuration = Column(JSONB, default=dict)
    capabilities = Column(JSONB, default=dict)

    # 통계 정보
    total_queries_executed = Column(BigInteger, default=0)
    total_results_returned = Column(BigInteger, default=0)
    average_response_time_ms = Column(Integer)
    success_rate = Column(Float, default=1.0)

    # 상태 관리
    is_active = Column(Boolean, default=True)
    is_deprecated = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    deprecated_at = Column(TIMESTAMP)

    # 메타데이터
    metadata_ = Column("metadata", JSONB, default=dict)

    # 관계
    queries = relationship("WebSearchQuery", back_populates="engine")


class WebSearchQuery(Base):
    """웹 검색 쿼리 로그"""
    __tablename__ = "web_search_queries"

    id = Column(Integer, primary_key=True)
    query_id = Column(String(255), unique=True, nullable=False)

    # 검색 쿼리 정보
    query_text = Column(Text, nullable=False)
    query_hash = Column(String(64), nullable=False)
    query_language = Column(String(10))
    query_intent = Column(String(100))

    # 검색 엔진 정보
    engine_id = Column(Integer, ForeignKey("search_engines.id", ondelete="RESTRICT"), nullable=False)
    engine_name = Column(String(100), nullable=False)

    # 사용자 및 세션 정보
    user_id = Column(String(255))
    session_id = Column(String(255))

    # 검색 실행 정보
    executed_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    execution_time_ms = Column(Integer)
    timeout_occurred = Column(Boolean, default=False)

    # 검색 파라미터
    search_params = Column(JSONB, default=dict)

    # 결과 통계
    total_results_count = Column(Integer, default=0)
    results_returned_count = Column(Integer, default=0)

    # 상태 및 품질
    status = Column(String(50), default='completed')
    error_message = Column(Text)
    quality_score = Column(Float)

    # 캐시 정보
    was_cached = Column(Boolean, default=False)
    cache_hit_at = Column(TIMESTAMP)

    # 추적 및 디버깅
    trace_id = Column(String(255))
    parent_query_id = Column(String(255), ForeignKey("web_search_queries.query_id", ondelete="SET NULL"))

    # 메타데이터
    metadata_ = Column("metadata", JSONB, default=dict)

    # 관계
    engine = relationship("SearchEngine", back_populates="queries")
    results = relationship("WebSearchResult", back_populates="query", cascade="all, delete-orphan")
    metrics = relationship("WebSearchMetric", back_populates="query", cascade="all, delete-orphan")
    parent_query = relationship("WebSearchQuery", remote_side=[query_id], backref="child_queries")


class WebSearchResult(Base):
    """웹 검색 결과 (시간에 따른 변화 추적)"""
    __tablename__ = "web_search_results"

    id = Column(Integer, primary_key=True)
    result_id = Column(String(255), unique=True, nullable=False)
    query_id = Column(String(255), ForeignKey("web_search_queries.query_id", ondelete="CASCADE"), nullable=False)

    # 결과 식별 정보
    result_url = Column(Text, nullable=False)
    url_hash = Column(String(64), nullable=False)
    result_position = Column(Integer)

    # 결과 내용
    result_title = Column(Text)
    result_content = Column(Text)
    result_summary = Column(Text)

    # 결과 메타데이터
    author = Column(String(500))
    published_date = Column(TIMESTAMP)
    last_modified_date = Column(TIMESTAMP)
    domain = Column(String(255))

    # 점수 및 품질
    relevance_score = Column(Float)
    quality_score = Column(Float)
    confidence_score = Column(Float)

    # 결과 타입 및 분류
    content_type = Column(String(100))
    content_category = Column(String(100))

    # 추가 구조화된 데이터
    structured_data = Column(JSONB, default=dict)
    extracted_entities = Column(JSONB, default=list)
    extracted_keywords = Column(JSONB, default=list)

    # 버전 관리
    result_version = Column(Integer, default=1)
    is_latest_version = Column(Boolean, default=True)
    content_hash = Column(String(64))

    # 타임스탬프
    first_seen_at = Column(TIMESTAMP, default=datetime.utcnow)
    captured_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)

    # 메타데이터
    metadata_ = Column("metadata", JSONB, default=dict)

    # 관계
    query = relationship("WebSearchQuery", back_populates="results")
    history = relationship("WebSearchResultHistory", back_populates="result", cascade="all, delete-orphan")
    source_relations = relationship(
        "WebSearchResultRelation",
        foreign_keys="[WebSearchResultRelation.source_result_id]",
        back_populates="source_result",
        cascade="all, delete-orphan"
    )
    target_relations = relationship(
        "WebSearchResultRelation",
        foreign_keys="[WebSearchResultRelation.target_result_id]",
        back_populates="target_result",
        cascade="all, delete-orphan"
    )


class WebSearchResultHistory(Base):
    """검색 결과 변경 이력"""
    __tablename__ = "web_search_result_history"

    id = Column(Integer, primary_key=True)
    result_id = Column(String(255), ForeignKey("web_search_results.result_id", ondelete="CASCADE"), nullable=False)

    # 변경 정보
    change_type = Column(String(50), nullable=False)
    changed_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)

    # 변경 전후 데이터
    old_data = Column(JSONB)
    new_data = Column(JSONB)

    # 변경 감지 방법
    detection_method = Column(String(100))

    # 메타데이터
    metadata_ = Column("metadata", JSONB, default=dict)

    # 관계
    result = relationship("WebSearchResult", back_populates="history")


class WebSearchResultRelation(Base):
    """검색 결과 간 관계"""
    __tablename__ = "web_search_result_relations"

    id = Column(Integer, primary_key=True)
    source_result_id = Column(String(255), ForeignKey("web_search_results.result_id", ondelete="CASCADE"), nullable=False)
    target_result_id = Column(String(255), ForeignKey("web_search_results.result_id", ondelete="CASCADE"), nullable=False)

    relation_type = Column(String(50), nullable=False)
    similarity_score = Column(Float)

    detected_at = Column(TIMESTAMP, default=datetime.utcnow)

    metadata_ = Column("metadata", JSONB, default=dict)

    # 관계
    source_result = relationship(
        "WebSearchResult",
        foreign_keys=[source_result_id],
        back_populates="source_relations"
    )
    target_result = relationship(
        "WebSearchResult",
        foreign_keys=[target_result_id],
        back_populates="target_relations"
    )


class WebSearchMetric(Base):
    """검색 성능 메트릭"""
    __tablename__ = "web_search_metrics"

    id = Column(Integer, primary_key=True)
    query_id = Column(String(255), ForeignKey("web_search_queries.query_id", ondelete="CASCADE"), nullable=False)

    # 성능 메트릭
    api_call_time_ms = Column(Integer)
    result_processing_time_ms = Column(Integer)
    total_time_ms = Column(Integer)

    # 리소스 사용
    memory_used_mb = Column(Float)
    network_bytes_sent = Column(Integer)
    network_bytes_received = Column(Integer)

    # 품질 메트릭
    results_relevance_avg = Column(Float)
    results_diversity_score = Column(Float)
    user_satisfaction_score = Column(Float)

    # 에러 및 재시도
    retry_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    recorded_at = Column(TIMESTAMP, default=datetime.utcnow)

    metadata_ = Column("metadata", JSONB, default=dict)

    # 관계
    query = relationship("WebSearchQuery", back_populates="metrics")
