from typing import TypedDict, List, Dict, Any, Optional, Annotated
from dataclasses import dataclass
from datetime import datetime
import operator


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

    # 쿼리 분류 결과
    query_classification: Optional[Dict[str, Any]]
    required_agents: List[str]
    
    # 각 에이전트 결과
    search_results: Annotated[List[SearchResult], operator.add]
    analysis_results: Annotated[List[AnalysisResult], operator.add]
    generation_results: Annotated[List[GenerationResult], operator.add]
    
    # 통합 및 검증
    integrated_results: Optional[Dict[str, Any]]
    quality_score: Optional[float]
    quality_feedback: Optional[str]
    
    # 최종 응답
    final_response: Optional[str]
    response_metadata: Optional[Dict[str, Any]]
    
    # 메타데이터
    execution_start: datetime
    execution_steps: List[Dict[str, Any]]
    errors: Annotated[List[str], operator.add]
    retry_count: int
    
    # 성능 지표
    execution_time_ms: Optional[int]
    tokens_used: Optional[int]
    api_calls_made: Optional[int]


class WorkflowConfig:
    """워크플로우 설정"""
    MAX_ITERATIONS = 10
    TIMEOUT_SECONDS = 300
    MIN_QUALITY_SCORE = 0.4  # Lower threshold to prevent infinite loops
    MAX_RETRIES = 2  # Maximum number of retries for quality improvement
    
    # 에이전트 타입
    SEARCH_AGENTS = [
        "knowledge_search",
        "realtime_info_search",
        "realtime_data_search",
        "multi_query_search",
        "deep_research"
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
        "multi_step_reasoning"
    ]
