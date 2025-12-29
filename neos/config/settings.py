from typing import Optional, List, Union
from pydantic_settings import BaseSettings
from pydantic import field_validator
import os
import dotenv

from neos.prompts.artifact import SYSTEM_PROMPT_FOR_ARTIFACT

dotenv.load_dotenv()
env_vars = os.environ


class Settings(BaseSettings):
    # 데이터베이스 설정
    DATABASE_URL: str = env_vars.get("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/ai_system")
    # 연결 풀 최적화: 총 50개 (20+30) 연결로 제한하여 DB 부하 방지
    # PostgreSQL default max_connections = 100 고려
    DATABASE_POOL_SIZE: int = int(env_vars.get("DATABASE_POOL_SIZE", 20))  # 개선: 40 → 20
    DATABASE_MAX_OVERFLOW: int = int(env_vars.get("DATABASE_MAX_OVERFLOW", 30))  # 개선: 80 → 30
    DATABASE_POOL_TIMEOUT: int = int(env_vars.get("DATABASE_POOL_TIMEOUT", 30))
    DATABASE_POOL_RECYCLE: int = int(env_vars.get("DATABASE_POOL_RECYCLE", 1800))  # 30분 (개선: 40분 → 30분)

    # Redis 설정
    REDIS_URL: str = env_vars.get("REDIS_URL", "redis://localhost:6379")
    REDIS_TTL: int = int(env_vars.get("REDIS_TTL", 3600))  # 1시간
    REDIS_POOL_SIZE: int = int(env_vars.get("REDIS_POOL_SIZE", 50))
    REDIS_MIN_IDLE_CONNECTIONS: int = int(env_vars.get("REDIS_MIN_IDLE_CONNECTIONS", 10))

    # 캐시 설정
    WORKFLOW_RESPONSE_CACHE_TTL: int = int(env_vars.get("WORKFLOW_RESPONSE_CACHE_TTL", 7200))  # 2시간
    USER_SPECIFIC_CACHE: bool = bool(env_vars.get("USER_SPECIFIC_CACHE", False))  # 사용자별 캐시 분리 (개인화된 응답 시 활성화)
    # Semantic Cache: 유사한 쿼리에 대한 응답 재사용으로 성능 향상
    SEMANTIC_CACHE_ENABLED: bool = bool(env_vars.get("SEMANTIC_CACHE_ENABLED", True))  # 개선: 기본값 활성화
    SEMANTIC_CACHE_THRESHOLD: float = float(env_vars.get("SEMANTIC_CACHE_THRESHOLD", 0.90))  # 개선: 0.95 → 0.90 (더 많은 캐시 히트)

    # 스마트 캐시 설정 (pgvector 기반 의미론적 캐싱 + 동적 TTL)
    SMART_CACHE_ENABLED: bool = bool(env_vars.get("SMART_CACHE_ENABLED", True))  # 스마트 캐시 활성화
    SMART_CACHE_SIMILARITY_THRESHOLD: float = float(env_vars.get("SMART_CACHE_SIMILARITY_THRESHOLD", 0.85))  # 유사도 임계값
    SMART_CACHE_MAX_ENTRIES: int = int(env_vars.get("SMART_CACHE_MAX_ENTRIES", 100000))  # 최대 캐시 엔트리 수
    SMART_CACHE_STATISTICS_ENABLED: bool = bool(env_vars.get("SMART_CACHE_STATISTICS_ENABLED", True))  # 통계 수집 활성화

    # 쿼리 유형별 동적 TTL 기본값 (초 단위, 환경변수로 오버라이드 가능)
    SMART_CACHE_TTL_REALTIME: int = int(env_vars.get("SMART_CACHE_TTL_REALTIME", 900))  # 15분 - 실시간 정보
    SMART_CACHE_TTL_FINANCIAL: int = int(env_vars.get("SMART_CACHE_TTL_FINANCIAL", 600))  # 10분 - 금융 데이터
    SMART_CACHE_TTL_ANALYSIS: int = int(env_vars.get("SMART_CACHE_TTL_ANALYSIS", 604800))  # 7일 - 분석 결과
    SMART_CACHE_TTL_RESEARCH: int = int(env_vars.get("SMART_CACHE_TTL_RESEARCH", 2592000))  # 30일 - 심층 연구
    SMART_CACHE_TTL_GENERATION: int = int(env_vars.get("SMART_CACHE_TTL_GENERATION", 7776000))  # 90일 - 생성 콘텐츠

    # AI 서비스 API 키
    OPENAI_API_KEY: str = env_vars.get("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: Optional[str] = env_vars.get("ANTHROPIC_API_KEY", None)
    GOOGLE_API_KEY: Optional[str] = env_vars.get("GOOGLE_API_KEY", None)
    TAVILY_API_KEY: str = env_vars.get("TAVILY_API_KEY", "")

    # 외부 API 키 설정
    # Weather API
    OPENWEATHER_API_KEY: str = env_vars.get("OPENWEATHER_API_KEY", "")

    # Currency Exchange API
    EXCHANGERATE_API_KEY: str = env_vars.get("EXCHANGERATE_API_KEY", "")

    # Stock Market APIs
    STOCK_API_PROVIDER: str = env_vars.get("STOCK_API_PROVIDER", "yahoo")  # "yahoo" or "financialdatasets"
    FINANCIALDATASETS_API_KEY: str = env_vars.get("FINANCIALDATASETS_API_KEY", "")
    ALPHA_VANTAGE_API_KEY: str = env_vars.get("ALPHA_VANTAGE_API_KEY", "")  # Optional backup for financial statements

    # LLM 설정
    LLM_PROVIDER: str = env_vars.get("LLM_PROVIDER", "anthropic")  # "openai" or "anthropic"
    LLM_MODEL: str = env_vars.get("LLM_MODEL", "gpt-4-turbo-preview")  # or "claude-3-sonnet-20240229"
    LLM_TEMPERATURE: float = float(env_vars.get("LLM_TEMPERATURE", 0.1))
    LLM_TIMEOUT: int = int(env_vars.get("LLM_TIMEOUT", 120))  # Default API timeout in seconds
    LLM_TIMEOUT_RESEARCH_PLANNING: int = int(env_vars.get("LLM_TIMEOUT_RESEARCH_PLANNING", 180))  # Longer timeout for complex research operations

    # 임베딩 설정
    EMBEDDING_PROVIDER: str = env_vars.get("EMBEDDING_PROVIDER", "openai")
    EMBEDDING_MODEL: str = env_vars.get("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMENSION: int = int(env_vars.get("EMBEDDING_DIMENSION", 1536))

    # Vision 모델 설정
    VISION_PROVIDER: str = env_vars.get("VISION_PROVIDER", "auto")  # "gpt4o", "claude", "auto"
    VISION_ENABLED: bool = bool(env_vars.get("VISION_ENABLED", True))  # Vision 모델 사용 여부
    VISION_MAX_TOKENS: int = int(env_vars.get("VISION_MAX_TOKENS", 1000))  # Vision 응답 최대 토큰
    VISION_IMAGE_DETAIL: str = env_vars.get("VISION_IMAGE_DETAIL", "auto")  # GPT-4o 이미지 상세도 (auto, low, high)

    # 에이전트 설정
    MAX_ITERATIONS: int = int(env_vars.get("MAX_ITERATIONS", 10))
    AGENT_TIMEOUT: int = int(env_vars.get("AGENT_TIMEOUT", 300))  # 5분 (기본값)

    # 에이전트별 타임아웃 설정 (초 단위) - 성능 최적화
    AGENT_TIMEOUTS: dict = {
        # 검색 에이전트 - 빠른 응답 필요 (단기 조치: LLM 처리 시간 고려하여 조정)
        "knowledge_search": int(env_vars.get("TIMEOUT_KNOWLEDGE_SEARCH", 20)),
        "realtime_info_search": int(env_vars.get("TIMEOUT_REALTIME_INFO_SEARCH", 30)),  # 20→30초 (LLM 처리 포함)
        "realtime_data_search": int(env_vars.get("TIMEOUT_REALTIME_DATA_SEARCH", 30)),  # 20→30초 (LLM 처리 포함)
        "multi_query_search": int(env_vars.get("TIMEOUT_MULTI_QUERY_SEARCH", 35)),  # 30→35초 (다중 쿼리 처리)
        "web_lookup": int(env_vars.get("TIMEOUT_WEB_LOOKUP", 15)),

        # 분석 에이전트 - 중간 수준 타임아웃
        "data_analysis": int(env_vars.get("TIMEOUT_DATA_ANALYSIS", 60)),
        "comparative_analysis": int(env_vars.get("TIMEOUT_COMPARATIVE_ANALYSIS", 60)),
        "web_content_analysis": int(env_vars.get("TIMEOUT_WEB_CONTENT_ANALYSIS", 45)),

        # 생성 에이전트 - 작업 유형별 차등
        "image_generation": int(env_vars.get("TIMEOUT_IMAGE_GENERATION", 120)),
        "api_call": int(env_vars.get("TIMEOUT_API_CALL", 30)),
        "file_processing": int(env_vars.get("TIMEOUT_FILE_PROCESSING", 90)),
        "task_creation": int(env_vars.get("TIMEOUT_TASK_CREATION", 30)),

        # Deep Research 에이전트 - 장시간 작업 허용
        "deep_research": int(env_vars.get("TIMEOUT_DEEP_RESEARCH", 300)),
        "hyper_deep_research": int(env_vars.get("TIMEOUT_HYPER_DEEP_RESEARCH", 600)),

        # Iterative Web Explorer - 반복적 탐색 작업
        "iterative_web_explorer": int(env_vars.get("TIMEOUT_ITERATIVE_WEB_EXPLORER", 180)),
    }

    # Iterative Web Explorer 설정
    # 탐색 파라미터
    ITERATIVE_EXPLORER_MAX_DEPTH: int = int(env_vars.get("ITERATIVE_EXPLORER_MAX_DEPTH", 5))
    ITERATIVE_EXPLORER_MAX_PAGES: int = int(env_vars.get("ITERATIVE_EXPLORER_MAX_PAGES", 20))
    ITERATIVE_EXPLORER_MAX_ITERATIONS: int = int(env_vars.get("ITERATIVE_EXPLORER_MAX_ITERATIONS", 10))
    ITERATIVE_EXPLORER_MIN_QUALITY: float = float(env_vars.get("ITERATIVE_EXPLORER_MIN_QUALITY", 0.75))
    ITERATIVE_EXPLORER_CONCURRENT_FETCHES: int = int(env_vars.get("ITERATIVE_EXPLORER_CONCURRENT_FETCHES", 3))

    # 타임아웃
    ITERATIVE_EXPLORER_TIMEOUT: int = int(env_vars.get("ITERATIVE_EXPLORER_TIMEOUT", 180))  # 3분
    ITERATIVE_EXPLORER_TAVILY_TIMEOUT: int = int(env_vars.get("ITERATIVE_EXPLORER_TAVILY_TIMEOUT", 30))  # Tavily API 타임아웃 30초

    # 캐시 TTL
    ITERATIVE_EXPLORER_CACHE_TTL: int = int(env_vars.get("ITERATIVE_EXPLORER_CACHE_TTL", 3600))  # 1시간
    ITERATIVE_EXPLORER_COMPLETENESS_CACHE_TTL: int = int(env_vars.get("ITERATIVE_EXPLORER_COMPLETENESS_CACHE_TTL", 1800))  # 30분

    # 링크 추출 설정
    ITERATIVE_EXPLORER_INITIAL_SEARCH_RESULTS: int = int(env_vars.get("ITERATIVE_EXPLORER_INITIAL_SEARCH_RESULTS", 10))
    ITERATIVE_EXPLORER_RECENT_RESULTS_WINDOW: int = int(env_vars.get("ITERATIVE_EXPLORER_RECENT_RESULTS_WINDOW", 5))
    ITERATIVE_EXPLORER_PAGE_LIMIT_THRESHOLD: float = float(env_vars.get("ITERATIVE_EXPLORER_PAGE_LIMIT_THRESHOLD", 0.9))

    # LinkFollower 설정
    LINK_FOLLOWER_MAX_LINKS: int = int(env_vars.get("LINK_FOLLOWER_MAX_LINKS", 10))
    LINK_FOLLOWER_MIN_RELEVANCE: float = float(env_vars.get("LINK_FOLLOWER_MIN_RELEVANCE", 0.5))

    # Quality Evaluator 설정
    # 가중치 (합이 1.0이어야 함)
    QUALITY_EVALUATOR_COMPLETENESS_WEIGHT: float = float(env_vars.get("QUALITY_EVALUATOR_COMPLETENESS_WEIGHT", 0.4))
    QUALITY_EVALUATOR_CREDIBILITY_WEIGHT: float = float(env_vars.get("QUALITY_EVALUATOR_CREDIBILITY_WEIGHT", 0.3))
    QUALITY_EVALUATOR_DIVERSITY_WEIGHT: float = float(env_vars.get("QUALITY_EVALUATOR_DIVERSITY_WEIGHT", 0.3))

    # 조기 종료 임계값
    QUALITY_EVALUATOR_EARLY_TERMINATION_THRESHOLD: float = float(env_vars.get("QUALITY_EVALUATOR_EARLY_TERMINATION_THRESHOLD", 0.3))

    # 신뢰도 평가
    QUALITY_EVALUATOR_HIGH_CREDIBILITY_THRESHOLD: float = float(env_vars.get("QUALITY_EVALUATOR_HIGH_CREDIBILITY_THRESHOLD", 0.7))

    # 다양성 평가
    QUALITY_EVALUATOR_DOMINANCE_THRESHOLD: float = float(env_vars.get("QUALITY_EVALUATOR_DOMINANCE_THRESHOLD", 0.5))

    # 검색 오케스트레이션 타임아웃 (즉시 조치: 20초 → 40초로 증가)
    # LLM 처리 시간을 고려하여 충분한 여유 확보
    SEARCH_ORCHESTRATION_TIMEOUT: int = int(env_vars.get("SEARCH_ORCHESTRATION_TIMEOUT", 40))

    # 동시성 설정
    MAX_CONCURRENT_WORKFLOWS: int = int(env_vars.get("MAX_CONCURRENT_WORKFLOWS", 100))
    MAX_CONCURRENT_AGENTS_PER_WORKFLOW: int = int(env_vars.get("MAX_CONCURRENT_AGENTS_PER_WORKFLOW", 10))

    # 스트리밍 설정
    STREAM_EVENT_TIMEOUT: float = float(env_vars.get("STREAM_EVENT_TIMEOUT", 2.0))  # SSE 이벤트 큐 대기 타임아웃 (초)
    STREAM_HEARTBEAT_INTERVAL: int = int(env_vars.get("STREAM_HEARTBEAT_INTERVAL", 30))  # SSE heartbeat 간격 (초)

    # API 설정
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = bool(env_vars.get("DEBUG", False))

    # API 게이트웨이 설정
    # 게이트웨이 모드가 활성화되면 X-User-ID 헤더를 신뢰합니다
    API_GATEWAY_ENABLED: bool = env_vars.get("API_GATEWAY_ENABLED", "false").lower() in ("true", "1", "yes")
    API_GATEWAY_USER_ID_HEADER: str = env_vars.get("API_GATEWAY_USER_ID_HEADER", "X-User-ID")
    # 게이트웨이에서만 요청을 받도록 허용할 IP 목록 (비어있으면 모든 IP 허용)
    API_GATEWAY_TRUSTED_IPS: Union[str, List[str]] = "127.0.0.1,::1"

    # 인증 설정
    JWT_SECRET_KEY: str = env_vars.get("JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(env_vars.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15))  # 15분
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(env_vars.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7))  # 7일

    # Google OAuth 설정
    GOOGLE_OAUTH_CLIENT_ID: str = env_vars.get("GOOGLE_OAUTH_CLIENT_ID", "")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # JWT Secret Key 필수 검증
        if not self.JWT_SECRET_KEY:
            raise ValueError(
                "JWT_SECRET_KEY must be set in environment variables. "
                "Generate a secure key with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

        # Quality Evaluator 가중치 합 검증
        weight_sum = (
            self.QUALITY_EVALUATOR_COMPLETENESS_WEIGHT +
            self.QUALITY_EVALUATOR_CREDIBILITY_WEIGHT +
            self.QUALITY_EVALUATOR_DIVERSITY_WEIGHT
        )
        if abs(weight_sum - 1.0) > 0.01:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Quality evaluator weights sum to {weight_sum:.3f}, not 1.0. "
                f"This may affect quality scoring accuracy. "
                f"(completeness={self.QUALITY_EVALUATOR_COMPLETENESS_WEIGHT}, "
                f"credibility={self.QUALITY_EVALUATOR_CREDIBILITY_WEIGHT}, "
                f"diversity={self.QUALITY_EVALUATOR_DIVERSITY_WEIGHT})"
            )

    # 비밀번호 정책
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_MAX_LENGTH: int = 72  # bcrypt maximum
    PASSWORD_REQUIRE_UPPERCASE: bool = False
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True

    # API 키 설정
    API_KEY_LENGTH: int = 32  # bytes
    API_KEY_PREFIX: str = "neos_"

    # 세션 설정
    SESSION_COOKIE_NAME: str = "neos_session"
    SESSION_EXPIRE_SECONDS: int = int(env_vars.get("SESSION_EXPIRE_SECONDS", 604800))  # 7일

    # Rate Limiting 설정
    RATE_LIMIT_LOGIN_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 600  # 10분
    RATE_LIMIT_API_CALLS_PER_MINUTE: int = 100

    # Circuit Breaker 설정
    CIRCUIT_BREAKER_ENABLED: bool = bool(env_vars.get("CIRCUIT_BREAKER_ENABLED", True))
    CIRCUIT_BREAKER_FAIL_THRESHOLD: int = int(env_vars.get("CIRCUIT_BREAKER_FAIL_THRESHOLD", 5))  # 연속 실패 횟수
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = int(env_vars.get("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", 60))  # 복구 시도 간격 (초)
    CIRCUIT_BREAKER_EXPECTED_EXCEPTION: bool = True  # 예외 발생 시 실패로 간주

    # CORS 설정
    CORS_ALLOWED_ORIGINS: Union[str, List[str]] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    @field_validator('CORS_ALLOWED_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v

    @field_validator('API_GATEWAY_TRUSTED_IPS', mode='before')
    @classmethod
    def parse_trusted_ips(cls, v):
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(',') if ip.strip()]
        return v

    # 로그 설정
    LOG_LEVEL: str = env_vars.get("LOG_LEVEL", "INFO")

    # 관찰 가능성(Observability) 설정
    OBSERVABILITY_ENABLED: bool = bool(env_vars.get("OBSERVABILITY_ENABLED", True))
    PHOENIX_HOST: str = env_vars.get("PHOENIX_HOST", "localhost")
    PHOENIX_PORT: int = int(env_vars.get("PHOENIX_PORT", 6006))
    PHOENIX_COLLECTOR_ENDPOINT: Optional[str] = None
    PHOENIX_PROJECT_NAME: str = "neos-multi-agent"

    # 메트릭 수집 설정
    METRICS_ENABLED: bool = bool(env_vars.get("METRICS_ENABLED", True))
    TRACE_ENABLED: bool = bool(env_vars.get("TRACE_ENABLED", True))
    MAX_TRACES: int = int(env_vars.get("MAX_TRACES", 1000))
    TRACE_RETENTION_DAYS: int = int(env_vars.get("TRACE_RETENTION_DAYS", 30))

    # 성능 모니터링 설정
    TRACK_LLM_CALLS: bool = True
    TRACK_AGENT_PERFORMANCE: bool = True
    TRACK_WORKFLOW_METRICS: bool = True

    # MCP (Model Context Protocol) 설정
    MCP_ENABLED: bool = bool(env_vars.get("MCP_ENABLED", True))
    MCP_SERVER_HOST: str = env_vars.get("MCP_SERVER_HOST", "localhost")
    MCP_SERVER_PORT: int = int(env_vars.get("MCP_SERVER_PORT", 8000))
    MCP_TIMEOUT: int = int(env_vars.get("MCP_TIMEOUT", 30))
    MCP_RETRY_COUNT: int = int(env_vars.get("MCP_RETRY_COUNT", 3))
    MCP_FALLBACK_ENABLED: bool = bool(env_vars.get("MCP_FALLBACK_ENABLED", True))

    # 도구 선택 설정
    TOOL_SELECTION_STRATEGY: str = env_vars.get("TOOL_SELECTION_STRATEGY", "mcp_fallback")  # always, mcp_available, mcp_fallback, preference_based
    TOOL_QUALITY_THRESHOLD: float = float(env_vars.get("TOOL_QUALITY_THRESHOLD", 0.7))
    TOOL_PERFORMANCE_PRIORITY: bool = bool(env_vars.get("TOOL_PERFORMANCE_PRIORITY", False))

    # 데이터셋 수집 설정
    DATASET_AUTO_SAVE: bool = bool(env_vars.get("DATASET_AUTO_SAVE", True))  # 워크플로우 실행 후 자동 저장
    DATASET_SAVE_FORMAT: str = env_vars.get("DATASET_SAVE_FORMAT", "jsonl")  # jsonl, json, csv
    DATASET_BASE_PATH: str = env_vars.get("DATASET_BASE_PATH", "datasets")  # 데이터셋 저장 경로

    # 웹 검색 로깅 설정
    WEB_SEARCH_LOG_ASYNC: bool = bool(env_vars.get("WEB_SEARCH_LOG_ASYNC", True))  # 비동기 로깅 활성화
    WEB_SEARCH_LOG_QUEUE_TYPE: str = env_vars.get("WEB_SEARCH_LOG_QUEUE_TYPE", "memory")  # memory, redis, kafka

    # 문서 스토리지 설정
    STORAGE_PROVIDER: str = env_vars.get("STORAGE_PROVIDER", "local")  # s3, rustfs, local

    # S3 설정
    S3_BUCKET_NAME: str = env_vars.get("S3_BUCKET_NAME", "neos-documents")
    S3_ENDPOINT_URL: Optional[str] = env_vars.get("S3_ENDPOINT_URL", None)  # S3-compatible endpoint
    AWS_REGION: str = env_vars.get("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID: Optional[str] = env_vars.get("AWS_ACCESS_KEY_ID", None)
    AWS_SECRET_ACCESS_KEY: Optional[str] = env_vars.get("AWS_SECRET_ACCESS_KEY", None)

    # rustfs 설정 (S3-compatible)
    RUSTFS_BUCKET_NAME: str = env_vars.get("RUSTFS_BUCKET_NAME", "neos-documents")
    RUSTFS_ENDPOINT_URL: Optional[str] = env_vars.get("RUSTFS_ENDPOINT_URL", None)
    RUSTFS_ACCESS_KEY: Optional[str] = env_vars.get("RUSTFS_ACCESS_KEY", None)
    RUSTFS_SECRET_KEY: Optional[str] = env_vars.get("RUSTFS_SECRET_KEY", None)

    # 로컬 스토리지 설정
    LOCAL_STORAGE_PATH: str = env_vars.get("LOCAL_STORAGE_PATH", "storage/documents")

    # 문서 처리 설정
    MAX_FILE_SIZE: int = int(env_vars.get("MAX_FILE_SIZE", 52428800))  # 50MB
    ALLOWED_FILE_EXTENSIONS: list = [".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".pptx"]

    # 문서 청킹 설정
    CHUNK_SIZE: int = int(env_vars.get("CHUNK_SIZE", 1000))  # 문자 수
    CHUNK_OVERLAP: int = int(env_vars.get("CHUNK_OVERLAP", 200))  # 문자 수

    # 지식 그래프 추출 설정
    KG_EXTRACTION_ENABLED: bool = bool(env_vars.get("KG_EXTRACTION_ENABLED", True))
    KG_EXTRACTION_MODEL: str = env_vars.get("KG_EXTRACTION_MODEL", "gpt-4-turbo-preview")
    KG_MIN_CONFIDENCE: float = float(env_vars.get("KG_MIN_CONFIDENCE", 0.7))

    # Deep Research 설정
    DEEP_RESEARCH_MAX_POLLING_DURATION: int = int(env_vars.get("DEEP_RESEARCH_MAX_POLLING_DURATION", 4800))  # 80분
    DEEP_RESEARCH_POLL_INTERVAL: int = int(env_vars.get("DEEP_RESEARCH_POLL_INTERVAL", 10))  # 10초
    DEEP_RESEARCH_DEFAULT_QUALITY_SCORE: float = float(env_vars.get("DEEP_RESEARCH_DEFAULT_QUALITY_SCORE", 0.85))
    DEEP_RESEARCH_CHUNK_SIZE: int = int(env_vars.get("DEEP_RESEARCH_CHUNK_SIZE", 200))
    DEEP_RESEARCH_MAX_SOURCES_IN_MEMORY: int = int(env_vars.get("DEEP_RESEARCH_MAX_SOURCES_IN_MEMORY", 50))
    DEEP_RESEARCH_MAX_CONCURRENT_REQUESTS: int = int(env_vars.get("DEEP_RESEARCH_MAX_CONCURRENT_REQUESTS", 3))
    DEEP_RESEARCH_MIN_REQUEST_INTERVAL: float = float(env_vars.get("DEEP_RESEARCH_MIN_REQUEST_INTERVAL", 0.5))

    # 환경 설정
    ENVIRONMENT: str = "development"  # development, staging, production

    # ============================================================================
    # Artifact (문서 생성) 설정
    # ============================================================================

    # 아티팩트 기능 활성화
    ARTIFACTS_ENABLED: bool = bool(env_vars.get("ARTIFACTS_ENABLED", True))

    # 아티팩트 LLM 모델 설정
    ARTIFACT_LLM_MODEL: str = env_vars.get("ARTIFACT_LLM_MODEL", "claude-haiku-4-5-20251001")
    ARTIFACT_LLM_TEMPERATURE: float = float(env_vars.get("ARTIFACT_LLM_TEMPERATURE", 0.7))
    ARTIFACT_LLM_MAX_TOKENS: int = int(env_vars.get("ARTIFACT_LLM_MAX_TOKENS", 4096))

    # 아티팩트 프롬프트
    ARTIFACTS_SYSTEM_PROMPT: str = SYSTEM_PROMPT_FOR_ARTIFACT

    # ============================================================================
    # Chat (채팅) 설정
    # ============================================================================

    # 채팅 기본 max_tokens 설정 (200K)
    CHAT_DEFAULT_MAX_TOKENS: int = int(env_vars.get("CHAT_DEFAULT_MAX_TOKENS", 200000))

    # 워크플로우 통합 활성화 (채팅에서 워크플로우 사용)
    ENABLE_WORKFLOW_IN_CHAT: bool = bool(env_vars.get("ENABLE_WORKFLOW_IN_CHAT", True))

    # Phase 3: 응답 정제 기능 활성화 (부분 성공 시 LLM으로 응답 정제)
    ENABLE_RESPONSE_REFINEMENT: bool = bool(env_vars.get("ENABLE_RESPONSE_REFINEMENT", True))

    # 컨텍스트 최적화 설정
    # 1. Thinking Block 관리
    THINKING_BLOCKS_ENABLED: bool = bool(env_vars.get("THINKING_BLOCKS_ENABLED", True))  # LLM thinking block 활성화
    MAX_THINKING_LENGTH: int = int(env_vars.get("MAX_THINKING_LENGTH", 0))  # 0 = unlimited, >0 = limit in chars

    # 추가 최적화: 워크플로우 단계별 Thinking blocks 비활성화
    # 검색 에이전트는 빠른 응답이 중요하므로 thinking blocks 비활성화
    DISABLE_THINKING_FOR_SEARCH: bool = bool(env_vars.get("DISABLE_THINKING_FOR_SEARCH", True))  # 검색 에이전트에서 thinking 비활성화

    # 2. 토큰 카운팅
    USE_TIKTOKEN: bool = bool(env_vars.get("USE_TIKTOKEN", True))  # tiktoken 사용 여부
    TOKEN_COUNTER_MODEL: str = env_vars.get("TOKEN_COUNTER_MODEL", "gpt-4")  # tiktoken 인코더 모델

    # 3. 컨텍스트 오버플로우 감지
    CONTEXT_OVERFLOW_DETECTION: bool = bool(env_vars.get("CONTEXT_OVERFLOW_DETECTION", True))  # 오버플로우 사전 감지
    CONTEXT_WINDOW_THRESHOLD: float = float(env_vars.get("CONTEXT_WINDOW_THRESHOLD", 0.85))  # 경고 임계값 (85%)
    MAX_CONTEXT_TOKENS: int = int(env_vars.get("MAX_CONTEXT_TOKENS", 800000))  # Claude Sonnet 4.5 기본값
    CONTEXT_RESERVE_TOKENS: int = int(env_vars.get("CONTEXT_RESERVE_TOKENS", 4096))  # 응답용 예비 토큰

    # 4. Tool Result 요약
    TOOL_RESULT_SUMMARIZATION: bool = bool(env_vars.get("TOOL_RESULT_SUMMARIZATION", True))  # Tool result 요약 활성화
    TOOL_RESULT_MAX_LENGTH: int = int(env_vars.get("TOOL_RESULT_MAX_LENGTH", 4000))  # Tool result 최대 길이
    TOOL_RESULT_SUMMARIZATION_MODEL: str = env_vars.get("TOOL_RESULT_SUMMARIZATION_MODEL", "gpt-4-turbo-preview")

    # 5. 메시지 압축
    MESSAGE_COMPRESSION_ENABLED: bool = bool(env_vars.get("MESSAGE_COMPRESSION_ENABLED", True))  # 메시지 압축 활성화
    MESSAGE_COMPRESSION_THRESHOLD: int = int(env_vars.get("MESSAGE_COMPRESSION_THRESHOLD", 30))  # N턴 이상에서 압축
    MESSAGE_COMPRESSION_RATIO: float = float(env_vars.get("MESSAGE_COMPRESSION_RATIO", 0.5))  # 압축 비율 (50%)
    MESSAGE_HISTORY_MAX_TOKENS: int = int(env_vars.get("MESSAGE_HISTORY_MAX_TOKENS", 50000))  # 히스토리 최대 토큰

    # 6. 의미론적 중복 제거
    SEMANTIC_DEDUPLICATION: bool = bool(env_vars.get("SEMANTIC_DEDUPLICATION", True))  # 의미 기반 중복 제거
    SEMANTIC_SIMILARITY_THRESHOLD: float = float(env_vars.get("SEMANTIC_SIMILARITY_THRESHOLD", 0.92))  # 유사도 임계값

    # 7. 워크플로우 컨텍스트 예산
    WORKFLOW_CONTEXT_BUDGET: bool = bool(env_vars.get("WORKFLOW_CONTEXT_BUDGET", True))  # 워크플로우별 예산 할당
    DEFAULT_WORKFLOW_TOKEN_BUDGET: int = int(env_vars.get("DEFAULT_WORKFLOW_TOKEN_BUDGET", 100000))  # 기본 토큰 예산
    DEEP_RESEARCH_TOKEN_BUDGET: int = int(env_vars.get("DEEP_RESEARCH_TOKEN_BUDGET", 150000))  # Deep Research 예산
    CHAT_TOKEN_BUDGET: int = int(env_vars.get("CHAT_TOKEN_BUDGET", 80000))  # 일반 채팅 예산

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables not defined in the model


# 전역 설정 인스턴스
settings = Settings()
