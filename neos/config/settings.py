from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import field_validator
import os
import dotenv


dotenv.load_dotenv()
env_vars = os.environ


class Settings(BaseSettings):
    # 데이터베이스 설정
    DATABASE_URL: str = env_vars.get("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/ai_system")
    DATABASE_POOL_SIZE: int = int(env_vars.get("DATABASE_POOL_SIZE", 40))
    DATABASE_MAX_OVERFLOW: int = int(env_vars.get("DATABASE_MAX_OVERFLOW", 80))
    DATABASE_POOL_TIMEOUT: int = int(env_vars.get("DATABASE_POOL_TIMEOUT", 30))
    DATABASE_POOL_RECYCLE: int = int(env_vars.get("DATABASE_POOL_RECYCLE", 2400))  # 40분

    # Redis 설정
    REDIS_URL: str = env_vars.get("REDIS_URL", "redis://localhost:6379")
    REDIS_TTL: int = int(env_vars.get("REDIS_TTL", 3600))  # 1시간
    REDIS_POOL_SIZE: int = int(env_vars.get("REDIS_POOL_SIZE", 50))
    REDIS_MIN_IDLE_CONNECTIONS: int = int(env_vars.get("REDIS_MIN_IDLE_CONNECTIONS", 10))

    # 캐시 설정
    WORKFLOW_RESPONSE_CACHE_TTL: int = int(env_vars.get("WORKFLOW_RESPONSE_CACHE_TTL", 7200))  # 2시간 (개선됨: 24시간 → 2시간)
    SEMANTIC_CACHE_ENABLED: bool = bool(env_vars.get("SEMANTIC_CACHE_ENABLED", False))
    SEMANTIC_CACHE_THRESHOLD: float = float(env_vars.get("SEMANTIC_CACHE_THRESHOLD", 0.95))

    # AI 서비스 API 키
    OPENAI_API_KEY: str = env_vars.get("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: Optional[str] = env_vars.get("ANTHROPIC_API_KEY", None)
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

    # 임베딩 설정
    EMBEDDING_MODEL: str = env_vars.get("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMENSION: int = int(env_vars.get("EMBEDDING_DIMENSION", 1536))

    # Vision 모델 설정
    VISION_PROVIDER: str = env_vars.get("VISION_PROVIDER", "auto")  # "gpt4o", "claude", "auto"
    VISION_ENABLED: bool = bool(env_vars.get("VISION_ENABLED", True))  # Vision 모델 사용 여부
    VISION_MAX_TOKENS: int = int(env_vars.get("VISION_MAX_TOKENS", 1000))  # Vision 응답 최대 토큰
    VISION_IMAGE_DETAIL: str = env_vars.get("VISION_IMAGE_DETAIL", "auto")  # GPT-4o 이미지 상세도 (auto, low, high)

    # 에이전트 설정
    MAX_ITERATIONS: int = int(env_vars.get("MAX_ITERATIONS", 10))
    AGENT_TIMEOUT: int = int(env_vars.get("AGENT_TIMEOUT", 300))  # 5분

    # 동시성 설정
    MAX_CONCURRENT_WORKFLOWS: int = int(env_vars.get("MAX_CONCURRENT_WORKFLOWS", 100))
    MAX_CONCURRENT_AGENTS_PER_WORKFLOW: int = int(env_vars.get("MAX_CONCURRENT_AGENTS_PER_WORKFLOW", 10))

    # API 설정
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = bool(env_vars.get("DEBUG", False))

    # 인증 설정
    JWT_SECRET_KEY: str = env_vars.get("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(env_vars.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15))  # 15분
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(env_vars.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7))  # 7일

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
    CORS_ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    @field_validator('CORS_ALLOWED_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
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

    # 컨텍스트 최적화 설정
    # 1. Thinking Block 관리
    THINKING_BLOCKS_ENABLED: bool = bool(env_vars.get("THINKING_BLOCKS_ENABLED", True))  # LLM thinking block 활성화
    MAX_THINKING_LENGTH: int = int(env_vars.get("MAX_THINKING_LENGTH", 0))  # 0 = unlimited, >0 = limit in chars

    # 2. 토큰 카운팅
    USE_TIKTOKEN: bool = bool(env_vars.get("USE_TIKTOKEN", True))  # tiktoken 사용 여부
    TOKEN_COUNTER_MODEL: str = env_vars.get("TOKEN_COUNTER_MODEL", "gpt-4")  # tiktoken 인코더 모델

    # 3. 컨텍스트 오버플로우 감지
    CONTEXT_OVERFLOW_DETECTION: bool = bool(env_vars.get("CONTEXT_OVERFLOW_DETECTION", True))  # 오버플로우 사전 감지
    CONTEXT_WINDOW_THRESHOLD: float = float(env_vars.get("CONTEXT_WINDOW_THRESHOLD", 0.85))  # 경고 임계값 (85%)
    MAX_CONTEXT_TOKENS: int = int(env_vars.get("MAX_CONTEXT_TOKENS", 200000))  # Claude Sonnet 4.5 기본값
    CONTEXT_RESERVE_TOKENS: int = int(env_vars.get("CONTEXT_RESERVE_TOKENS", 4096))  # 응답용 예비 토큰

    # 4. Tool Result 요약
    TOOL_RESULT_SUMMARIZATION: bool = bool(env_vars.get("TOOL_RESULT_SUMMARIZATION", True))  # Tool result 요약 활성화
    TOOL_RESULT_MAX_LENGTH: int = int(env_vars.get("TOOL_RESULT_MAX_LENGTH", 500))  # Tool result 최대 길이
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


# 전역 설정 인스턴스
settings = Settings()
