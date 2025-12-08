"""Analytics models for the backoffice system."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AnalysisStatus(str, Enum):
    """Status of an analysis run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FacetType(str, Enum):
    """Types of facets that can be extracted."""

    TOPIC = "topic"
    LANGUAGE = "language"
    TASK_TYPE = "task_type"
    INTENT = "intent"
    SAFETY_SCORE = "safety_score"
    SENTIMENT = "sentiment"
    COMPLEXITY = "complexity"
    DOMAIN = "domain"
    CUSTOM = "custom"


class AnalysisRun(Base):
    """Represents a single analysis run of the pipeline."""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=AnalysisStatus.PENDING)

    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    facet_types: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # Time range for analysis
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Statistics
    total_conversations: Mapped[int] = mapped_column(Integer, default=0)
    processed_conversations: Mapped[int] = mapped_column(Integer, default=0)
    total_clusters: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    # Progress tracking
    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    clusters: Mapped[List["Cluster"]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan"
    )


class Facet(Base):
    """Definition of a facet type used in analysis."""

    __tablename__ = "facets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    facet_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # LLM prompt configuration
    extraction_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(50), default="string")  # string, number, boolean, list

    # Configuration
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    values: Mapped[List["FacetValue"]] = relationship(
        back_populates="facet", cascade="all, delete-orphan"
    )


class FacetValue(Base):
    """Possible values for a facet."""

    __tablename__ = "facet_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facet_id: Mapped[int] = mapped_column(Integer, ForeignKey("facets.id"), index=True)
    value: Mapped[str] = mapped_column(String(500))
    normalized_value: Mapped[str] = mapped_column(String(500), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)

    # Embedding for similarity matching
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(384), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    facet: Mapped["Facet"] = relationship(back_populates="values")

    __table_args__ = (
        UniqueConstraint("facet_id", "normalized_value", name="uq_facet_value"),
    )


class ConversationFacet(Base):
    """Extracted facets for a conversation."""

    __tablename__ = "conversation_facets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    analysis_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_runs.id"), index=True
    )

    # Extracted facets stored as JSONB
    facets: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Summary embedding for clustering
    summary_embedding: Mapped[Optional[List[float]]] = mapped_column(
        Vector(384), nullable=True
    )

    # UMAP coordinates for visualization
    umap_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    umap_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Cluster assignment
    cluster_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("clusters.id"), nullable=True, index=True
    )

    # Privacy flag (excluded if true)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    cluster: Mapped[Optional["Cluster"]] = relationship(back_populates="conversation_facets")

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "analysis_run_id", name="uq_conversation_analysis"
        ),
    )


class Cluster(Base):
    """A cluster of similar conversations."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    analysis_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_runs.id"), index=True
    )

    # Cluster information
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Hierarchy
    level: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("clusters.id"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(500), default="/")  # e.g., "/1/3/7"

    # Statistics
    conversation_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_user_count: Mapped[int] = mapped_column(Integer, default=0)

    # Centroid for visualization
    centroid_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    centroid_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    centroid_embedding: Mapped[Optional[List[float]]] = mapped_column(
        Vector(384), nullable=True
    )

    # Representative facets
    top_facets: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Keywords/topics
    keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)

    # Privacy validation
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    privacy_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="clusters")
    parent: Mapped[Optional["Cluster"]] = relationship(
        "Cluster", remote_side=[id], back_populates="children"
    )
    children: Mapped[List["Cluster"]] = relationship(
        "Cluster", back_populates="parent", cascade="all, delete-orphan"
    )
    conversation_facets: Mapped[List["ConversationFacet"]] = relationship(
        back_populates="cluster"
    )


class ClusterHierarchy(Base):
    """Materialized view of cluster hierarchy for fast traversal."""

    __tablename__ = "cluster_hierarchy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(Integer, index=True)
    cluster_id: Mapped[int] = mapped_column(Integer, index=True)
    ancestor_id: Mapped[int] = mapped_column(Integer, index=True)
    depth: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "cluster_id", "ancestor_id", name="uq_cluster_ancestor"
        ),
    )
