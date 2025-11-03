"""Query API Pydantic models"""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000, description="사용자 쿼리")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="사용자 설정")


class QueryResponse(BaseModel):
    success: bool
    response: str
    session_id: str
    query_id: Optional[int] = None
    metadata: Dict[str, Any]
    execution_time_ms: int
    quality_score: float
    errors: List[str] = Field(default_factory=list)


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, bool]


class TrendingQuery(BaseModel):
    query_text: str
    search_count: int
    last_searched: str
    category: Optional[str] = None


class RelatedQuery(BaseModel):
    query_text: str
    similarity_score: float
    relation_type: str


class HyperResearchReportResponse(BaseModel):
    success: bool
    report_id: str
    markdown_content: str
    metadata: Dict[str, Any]


class HyperResearchReportSummary(BaseModel):
    report_id: str
    report_uuid: str
    research_topic: str
    research_status: str
    created_at: str
    completed_at: Optional[str]
    total_sections: int
    total_sources: int
    total_queries: int
    quality_score: Optional[float]


class HyperResearchReportsListResponse(BaseModel):
    success: bool
    reports: List[HyperResearchReportSummary]
    total_count: int
