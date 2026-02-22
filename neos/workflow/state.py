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
