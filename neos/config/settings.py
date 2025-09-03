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
    OPENAI_API_KEY: str
    ANTHROPIC_API_KEY: Optional[str] = None
    TAVILY_API_KEY: str
    
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
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 전역 설정 인스턴스
settings = Settings()
