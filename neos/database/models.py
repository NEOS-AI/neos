from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Float, ForeignKey, ARRAY, Boolean # JSON,
from sqlalchemy.dialects.postgresql import JSONB #, UUID,
from sqlalchemy.orm import relationship
from datetime import datetime
from pgvector.sqlalchemy import Vector
# import uuid

from .connection import Base


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), unique=True, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    preferences = Column(JSONB, default=dict)
    
    # 관계
    query_histories = relationship("QueryHistory", back_populates="user")
    search_sessions = relationship("SearchSession", back_populates="user")

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
    chunk_size = Column(Integer)  # 문자 수

    # 위치 정보
    page_number = Column(Integer)
    start_offset = Column(Integer)
    end_offset = Column(Integer)

    # 임베딩
    embedding = Column(Vector(1536))  # OpenAI embedding

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
