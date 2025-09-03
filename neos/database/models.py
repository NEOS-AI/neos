from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Float, ForeignKey, ARRAY # JSON,
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
