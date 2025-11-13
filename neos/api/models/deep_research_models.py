"""Deep Research API Pydantic models"""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class ResearchStatus(str, Enum):
    """Deep research status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchPhase(str, Enum):
    """Deep research phases"""
    TOPIC_CONFIRMATION = "topic_confirmation"
    PLANNING = "planning"
    DATA_COLLECTION = "data_collection"
    ANALYSIS = "analysis"
    REPORT_GENERATION = "report_generation"


class SectionType(str, Enum):
    """Section types"""
    PLANNING = "planning"
    DATA_COLLECTION = "data_collection"
    ANALYSIS = "analysis"
    REPORT_GENERATION = "report_generation"


class SectionStatus(str, Enum):
    """Section status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# Request Models
# ============================================================================

class StartDeepResearchRequest(BaseModel):
    """Start deep research request"""
    user_id: str = Field(..., description="User ID")
    conversation_id: str = Field(..., description="Conversation ID")
    initial_message_id: str = Field(..., description="Initial message ID that triggered research")
    research_topic: str = Field(..., min_length=1, description="Research topic")
    session_id: Optional[str] = Field(None, description="Session ID for tracking")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class GetResearchStatusRequest(BaseModel):
    """Get research status request"""
    report_id: str = Field(..., description="Report ID")


# ============================================================================
# Response Models
# ============================================================================

class ResearchSection(BaseModel):
    """Research section response"""
    section_id: str = Field(..., description="Section ID")
    section_order: int = Field(..., description="Section order")
    section_level: int = Field(..., description="Section level (hierarchy)")
    section_type: SectionType = Field(..., description="Section type")
    section_title: str = Field(..., description="Section title")
    section_content: Optional[str] = Field(None, description="Section content")
    section_summary: Optional[str] = Field(None, description="Section summary")
    section_status: SectionStatus = Field(..., description="Section status")
    sources_count: int = Field(default=0, description="Number of sources used")
    created_at: datetime = Field(..., description="Creation timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")


class ResearchReport(BaseModel):
    """Research report response"""
    report_id: str = Field(..., description="Report ID")
    user_id: str = Field(..., description="User ID")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")
    initial_message_id: Optional[str] = Field(None, description="Initial message ID")
    session_id: str = Field(..., description="Session ID")
    research_topic: str = Field(..., description="Research topic")
    research_status: ResearchStatus = Field(..., description="Research status")
    research_plan: Optional[Dict[str, Any]] = Field(None, description="Research plan")
    total_sections: int = Field(default=0, description="Total sections")
    total_sources: int = Field(default=0, description="Total sources")
    total_queries: int = Field(default=0, description="Total queries executed")
    quality_score: Optional[float] = Field(None, description="Quality score")
    completeness_score: Optional[float] = Field(None, description="Completeness score")
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")
    created_at: datetime = Field(..., description="Creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    sections: List[ResearchSection] = Field(default_factory=list, description="Research sections")


class StartDeepResearchResponse(BaseModel):
    """Start deep research response"""
    success: bool = Field(..., description="Success status")
    report_id: str = Field(..., description="Report ID")
    research_topic: str = Field(..., description="Research topic")
    research_status: ResearchStatus = Field(..., description="Initial status")
    message: str = Field(..., description="Response message")
    stream_url: Optional[str] = Field(None, description="SSE stream URL for progress updates")


# ============================================================================
# SSE Event Models
# ============================================================================

class DeepResearchEventType(str, Enum):
    """Deep research SSE event types"""
    STARTED = "started"
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    SECTION_STARTED = "section_started"
    SECTION_COMPLETED = "section_completed"
    SECTION_CONTENT = "section_content"
    QUERY_EXECUTED = "query_executed"
    PROGRESS_UPDATE = "progress_update"
    ERROR = "error"
    COMPLETED = "completed"
    FAILED = "failed"


class DeepResearchEvent(BaseModel):
    """Deep research SSE event"""
    event: DeepResearchEventType = Field(..., description="Event type")
    report_id: str = Field(..., description="Report ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="Event timestamp")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event data")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class PhaseStartedEventData(BaseModel):
    """Phase started event data"""
    phase: ResearchPhase = Field(..., description="Research phase")
    message: str = Field(..., description="Phase message")


class PhaseCompletedEventData(BaseModel):
    """Phase completed event data"""
    phase: ResearchPhase = Field(..., description="Research phase")
    message: str = Field(..., description="Phase message")
    duration_ms: int = Field(..., description="Phase duration in milliseconds")


class SectionStartedEventData(BaseModel):
    """Section started event data"""
    section_id: str = Field(..., description="Section ID")
    section_title: str = Field(..., description="Section title")
    section_type: SectionType = Field(..., description="Section type")


class SectionCompletedEventData(BaseModel):
    """Section completed event data"""
    section_id: str = Field(..., description="Section ID")
    section_title: str = Field(..., description="Section title")
    section_type: SectionType = Field(..., description="Section type")
    section_content: str = Field(..., description="Section content")
    sources_count: int = Field(..., description="Number of sources")


class SectionContentEventData(BaseModel):
    """Section content streaming event data"""
    section_id: str = Field(..., description="Section ID")
    content_chunk: str = Field(..., description="Content chunk")
    is_final: bool = Field(default=False, description="Is this the final chunk")


class QueryExecutedEventData(BaseModel):
    """Query executed event data"""
    query: str = Field(..., description="Search query")
    query_type: str = Field(..., description="Query type")
    results_count: int = Field(..., description="Number of results")


class ProgressUpdateEventData(BaseModel):
    """Progress update event data"""
    current_phase: ResearchPhase = Field(..., description="Current phase")
    completed_sections: int = Field(..., description="Completed sections")
    total_sections: int = Field(..., description="Total sections")
    sources_collected: int = Field(..., description="Sources collected")
    queries_executed: int = Field(..., description="Queries executed")
    progress_percentage: float = Field(..., description="Progress percentage (0-100)")
    estimated_time_remaining_seconds: Optional[int] = Field(None, description="Estimated time remaining")


class CompletedEventData(BaseModel):
    """Completed event data"""
    report_id: str = Field(..., description="Report ID")
    total_sections: int = Field(..., description="Total sections")
    total_sources: int = Field(..., description="Total sources")
    total_queries: int = Field(..., description="Total queries")
    quality_score: Optional[float] = Field(None, description="Quality score")
    processing_time_ms: int = Field(..., description="Processing time")


class ErrorEventData(BaseModel):
    """Error event data"""
    error_message: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Error code")
    phase: Optional[ResearchPhase] = Field(None, description="Phase where error occurred")
