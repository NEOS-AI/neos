"""Application configuration settings."""

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the base directory (backoffice/backend)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

# Print debug info at module load time (only if DEBUG=True in environment)
DEBUG_CONFIG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
if DEBUG_CONFIG and not any('pytest' in arg for arg in sys.argv):
    print(f"[Config] BASE_DIR: {BASE_DIR}")
    print(f"[Config] ENV_FILE: {ENV_FILE}")
    print(f"[Config] ENV_FILE exists: {ENV_FILE.exists()}")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "Analytics Backoffice"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALGORITHM: str = "HS256"

    # Database (shared with main neos)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/neos"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str = "redis://localhost:6379/1"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # LLM Configuration
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    LLM_MODEL: str = "claude-3-sonnet-20240229"
    EMBEDDING_MODEL: str = "all-mpnet-base-v2"

    # Clustering Configuration
    MIN_CLUSTER_SIZE: int = 10
    MIN_SAMPLES: int = 5
    CLUSTER_SELECTION_EPSILON: float = 0.0
    UMAP_N_NEIGHBORS: int = 15
    UMAP_MIN_DIST: float = 0.1
    UMAP_N_COMPONENTS: int = 2

    # Privacy Configuration
    PRIVACY_MIN_USERS_PER_CLUSTER: int = 1000
    PRIVACY_MIN_CONVERSATIONS_PER_CLUSTER: int = 100
    PII_DETECTION_ENABLED: bool = True

    # Pipeline Configuration
    BATCH_SIZE: int = 100
    MAX_CONVERSATIONS_PER_RUN: int = 10000

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    _settings = Settings()

    # Print loaded settings for debugging (only if DEBUG=True)
    if _settings.DEBUG and not any('pytest' in arg for arg in sys.argv):
        print("[Config] Settings loaded successfully")
        print(f"[Config] DATABASE_URL: {_settings.DATABASE_URL}")
        print(f"[Config] REDIS_URL: {_settings.REDIS_URL}")
        print(f"[Config] Using .env file: {ENV_FILE.exists()}")

    return _settings


settings = get_settings()
