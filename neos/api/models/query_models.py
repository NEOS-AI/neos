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


# ============================================================================
# Workflow Streaming Models
# ============================================================================

class WorkflowStreamEventType(str):
    """워크플로우 스트리밍 이벤트 타입"""
    STARTED = "started"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETED = "agent_completed"
    CONTENT_CHUNK = "content_chunk"
    PROGRESS_UPDATE = "progress_update"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    COMPLETED = "completed"
    # Phase 2 (OpenClaw Execution Approval): 사용자 승인 요청 이벤트
    # 클라이언트는 이 이벤트를 받으면 POST /api/v1/approval/respond를 호출해야 한다.
    APPROVAL_REQUEST = "approval_request"
    # Phase 8 (OpenClaw A2UI): UIFrame 이벤트
    # 클라이언트는 이 이벤트를 받으면 UIFrameRenderer로 폼을 렌더링하고,
    # 사용자 제출 후 POST /api/v1/ui/submit을 호출해야 한다.
    UI_FRAME = "ui_frame"
    UI_FRAME_UPDATE = "ui_frame_update"  # 향후 점진적 업데이트


class WorkflowStreamEvent(BaseModel):
    """워크플로우 스트리밍 이벤트"""
    event: str  # WorkflowStreamEventType 값
    session_id: str
    timestamp: str = Field(default_factory=lambda: __import__('datetime').datetime.now().isoformat())
    data: Dict[str, Any] = Field(default_factory=dict)

    # 노드/에이전트 정보
    node_name: Optional[str] = None
    agent_name: Optional[str] = None

    # 진행 상황
    progress_percent: Optional[int] = None
    current_step: Optional[str] = None
    total_steps: Optional[int] = None

    # 결과 데이터
    content: Optional[str] = None
    partial_response: Optional[str] = None
    error: Optional[str] = None

    # 메타데이터
    execution_time_ms: Optional[int] = None
    tokens_used: Optional[int] = None


class WorkflowStreamRequest(BaseModel):
    """워크플로우 스트리밍 요청"""
    query: str = Field(..., min_length=1, max_length=10000, description="사용자 쿼리")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="사용자 설정")
    stream_options: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {
            "include_heartbeat": True,
            "heartbeat_interval_ms": 5000,
            "include_agent_progress": True,
            "include_partial_content": True
        },
        description="스트리밍 옵션"
    )
