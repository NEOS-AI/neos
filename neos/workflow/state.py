from typing import TypedDict, List, Dict, Any, Optional, Annotated, Union
from dataclasses import dataclass
from datetime import datetime
import operator

from neos.config.settings import settings
from neos.workflow.errors import WorkflowError
from neos.workflow.metrics import PerformanceMetrics


@dataclass
class SearchResult:
    """검색 결과"""
    source: str
    title: str
    content: str
    url: Optional[str] = None
    score: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Convert numpy types to native Python types for msgpack serialization"""
        self.score = float(self.score)

@dataclass
class AnalysisResult:
    """분석 결과"""
    analysis_type: str
    data: Dict[str, Any]
    confidence: float
    insights: List[str]

    def __post_init__(self):
        """Convert numpy types to native Python types for msgpack serialization"""
        self.confidence = float(self.confidence)

@dataclass
class GenerationResult:
    """생성 결과"""
    content_type: str
    content: Any
    metadata: Dict[str, Any] = None

class AgentState(TypedDict):
    # 입력 관련
    user_id: str
    session_id: str
    original_query: str
    query_intent: Optional[str]
    query_embedding: Optional[List[float]]
    detected_language: Optional[str]  # 감지된 사용자 질문 언어

    # 채팅 히스토리 관련
    chat_history: Optional[List[Dict[str, Any]]]  # 대화 히스토리
    conversation_context: Optional[str]  # LLM이 생성한 대화 맥락 요약
    enable_history_context: Optional[bool]  # 히스토리 활용 여부
    history_metadata: Optional[Dict[str, Any]]  # 히스토리 메타데이터

    # 쿼리 분류 결과
    query_classification: Optional[Dict[str, Any]]
    required_agents: List[str]

    # Skill and tool selection
    selected_skills: Optional[List[str]]
    selected_tools: Optional[List[str]]
    selection_reasoning: Optional[str]

    # 각 에이전트 결과
    search_results: Annotated[List[SearchResult], operator.add]
    analysis_results: Annotated[List[AnalysisResult], operator.add]
    generation_results: Annotated[List[GenerationResult], operator.add]

    # Phase 2: 검색 결과 종합 (LLM 기반)
    search_synthesis: Optional[str]  # LLM이 생성한 검색 결과 종합 요약
    search_metadata: Optional[Dict[str, Any]]  # 검색 메타데이터 (성공/실패 정보 등)

    # 통합 및 검증
    integrated_results: Optional[Dict[str, Any]]
    quality_score: Optional[float]
    quality_feedback: Optional[str]

    # Fact-check 결과 (Phase 1)
    fact_check_result: Optional[Dict[str, Any]]
    fact_check_skipped: Optional[bool]

    # 반복적 탐색 상태 (Iterative Web Explorer)
    use_iterative_search: Optional[bool]  # 사용자 선호
    exploration_depth_reached: Optional[int]  # 도달 깊이
    exploration_pages_visited: Optional[int]  # 방문 페이지 수
    quality_evolution: Optional[List[float]]  # 반복별 품질 점수

    # Phase 2: 메모리 컨텍스트 (3계층 메모리 시스템)
    memory_context: Optional[Dict[str, Any]]

    # Phase 2.2: Multi-Round Research Sessions
    is_continuation: Optional[bool]
    research_session_id: Optional[str]
    accumulated_knowledge: Optional[Dict[str, Any]]
    explored_subtopics: Optional[List[str]]
    remaining_questions: Optional[List[str]]

    # Phase 2.6: Self-Reflection
    reflection_result: Optional[Dict[str, Any]]

    # Phase 2.4: Adaptive Replanning
    research_plan: Optional[List[Dict[str, Any]]]
    replan_count: Optional[int]
    answered_questions: Optional[List[str]]

    # Phase 2.5: Hypothesis-Driven Research
    hypotheses: Optional[List[Dict[str, Any]]]
    hypothesis_results: Optional[Dict[str, Any]]

    # Phase 2.7: Cost-Aware Routing
    cost_budget: Optional[float]
    cumulative_cost: Optional[float]
    cost_tracking: Optional[Dict[str, float]]

    # Phase 2.10: Executive Summary
    executive_summary: Optional[str]

    # Phase 4.7: Research Templates
    template_id: Optional[str]
    template_config: Optional[Dict[str, Any]]

    # Phase 2: Execution Approval (OpenClaw Exec Approval System)
    # pending_approvals: 승인 대기 중인 스킬 목록 [{request_id, skill_name, params, timeout_seconds}]
    # approval_decision: "approved" | "rejected" | None (interrupt 해제 후 채워짐)
    # ⚠️ operator.add 사용 안 함 — 누적이 아닌 교체형 필드
    pending_approvals: Optional[List[Dict[str, Any]]]
    approval_decision: Optional[str]
    approval_outcome: Optional[str]  # "approved" | "rejected" — _should_continue_after_approval 라우팅 전용

    # Phase 8: A2UI (Agent-to-User Interface)
    # needs_ui:      QueryClassifier가 True로 설정 → UI_FRAME_GENERATOR 단락 경로 진입
    # ui_frame:      UIFrameGenerator 출력 (UIFrame.dict() 직렬화)
    # ui_submission: 사용자 폼 제출값 (POST /api/v1/ui/submit에서 채워짐)
    # ⚠️ operator.add 사용 안 함 — 누적이 아닌 교체형 필드
    needs_ui: Optional[bool]
    ui_frame: Optional[Dict[str, Any]]
    ui_submission: Optional[Dict[str, Any]]

    # Phase 3: Context Assembly Engine (OpenClaw 컨텍스트 엔진 분리)
    assembled_context: Optional[Dict[str, Any]]          # ContextAssemblyEngine.trimmed 결과
    channel_type: Optional[str]                          # 요청 채널 "api"|"telegram"|"discord"|"slack"
    channel_id: Optional[str]                            # 외부 채널 식별자 (Telegram chat_id 등)
    channel_source: Optional[str]                        # query_history.channel_source: "api"|"telegram"|"discord"|"slack"

    # ROMA: Recursive Open Meta-Agent
    recursive_task_tree: Optional[Dict[str, Any]]       # 전체 태스크 트리 (직렬화된 RecursiveTaskNode)
    recursive_current_depth: Optional[int]              # 현재 재귀 깊이
    recursive_max_depth: Optional[int]                  # 최대 재귀 깊이
    recursive_task_stack: Optional[List[Dict]]          # 실행 중인 태스크 스택
    recursive_completed_tasks: Optional[List[Dict]]     # 완료된 태스크 목록
    recursive_mode: Optional[bool]                      # 재귀 모드 활성화 여부
    recursive_budget_remaining: Optional[float]         # 가용 비용 (USD)

    # 최종 응답
    final_response: Optional[str]
    response_metadata: Optional[Dict[str, Any]]

    # 메타데이터 및 에러 처리
    execution_start: datetime
    execution_steps: List[Dict[str, Any]]
    errors: Annotated[List[str], operator.add]  # Legacy string errors (deprecated)
    structured_errors: Annotated[List[WorkflowError], operator.add]  # Structured errors with metadata
    retry_count: int
    
    # 성능 지표 (Legacy - deprecated, use performance_metrics instead)
    execution_time_ms: Optional[int]
    tokens_used: Optional[int]
    api_calls_made: Optional[int]

    # 상세 성능 메트릭 (새로운 구조화된 메트릭 시스템)
    performance_metrics: Optional[PerformanceMetrics]


class WorkflowConfig:
    """워크플로우 설정

    중앙 집중화된 설정을 settings에서 가져와 사용합니다.
    환경 변수를 통해 동적으로 조정 가능합니다.
    """
    # 워크플로우 실행 제한 (settings에서 가져옴)
    MAX_ITERATIONS = settings.WORKFLOW_MAX_ITERATIONS
    TIMEOUT_SECONDS = settings.WORKFLOW_TIMEOUT_SECONDS
    MIN_QUALITY_SCORE = settings.WORKFLOW_MIN_QUALITY_SCORE
    MAX_RETRIES = settings.WORKFLOW_MAX_RETRIES
    
    # 에이전트 타입
    SEARCH_AGENTS = [
        "knowledge_search",
        "realtime_info_search",
        "realtime_data_search",
        "multi_query_search",
        "deep_research",
        "web_lookup",
        "youtube_search"
    ]
    
    ANALYSIS_AGENTS = [
        "data_analysis",
        "comparative_analysis"
    ]
    
    GENERATION_AGENTS = [
        "image_generation",
        "api_call",
        "file_processing",
        "task_creation"
    ]
    
    # 쿼리 의도 분류
    QUERY_INTENTS = [
        "information_seeking",
        "data_analysis",
        "comparison",
        "generation",
        "task_execution",
        "multi_step_reasoning",
        "youtube_search"
    ]
