"""Query API Pydantic models"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, bool]


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
    # Phase 3b (D23): deep analysis job이 제출됐음을 알리는 핸들 이벤트.
    # 클라이언트는 이 이벤트의 events_url로 별도 SSE를 열어 진행을 관찰한다.
    DEEP_ANALYSIS_STARTED = "deep_analysis_started"
    # 트랙 I: 설계 그래프 서브에이전트 노드의 걸음·폴드 (`neos:graph_subagent`).
    GRAPH_SUBAGENT = "graph_subagent"


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
