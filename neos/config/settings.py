from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 데이터베이스 설정
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/ai_system"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    
    # Redis 설정
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_TTL: int = 3600  # 1시간

    # AI 서비스 API 키
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: Optional[str] = None
    TAVILY_API_KEY: str = ""

    # LLM 설정
    LLM_PROVIDER: str = "openai"  # "openai" or "anthropic"
    LLM_MODEL: str = "gpt-4-turbo-preview"  # or "claude-3-sonnet-20240229"
    LLM_TEMPERATURE: float = 0.1

    # 임베딩 설정
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536

    # 에이전트 설정
    MAX_ITERATIONS: int = 10
    AGENT_TIMEOUT: int = 300  # 5분

    # API 설정
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # 로그 설정
    LOG_LEVEL: str = "INFO"

    # 관찰 가능성(Observability) 설정
    OBSERVABILITY_ENABLED: bool = True
    PHOENIX_HOST: str = "localhost"
    PHOENIX_PORT: int = 6006
    PHOENIX_COLLECTOR_ENDPOINT: Optional[str] = None
    PHOENIX_PROJECT_NAME: str = "neos-multi-agent"

    # 메트릭 수집 설정
    METRICS_ENABLED: bool = True
    TRACE_ENABLED: bool = True
    MAX_TRACES: int = 1000
    TRACE_RETENTION_DAYS: int = 30

    # 성능 모니터링 설정
    TRACK_LLM_CALLS: bool = True
    TRACK_AGENT_PERFORMANCE: bool = True
    TRACK_WORKFLOW_METRICS: bool = True

    # 환경 설정
    ENVIRONMENT: str = "development"  # development, staging, production
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 전역 설정 인스턴스
settings = Settings()
