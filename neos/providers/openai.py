"""OpenAIProvider — OpenAI GPT 모델 프로바이더

Phase 5 (OpenClaw ModelProvider 플러그인)
"""

from typing import Any, List

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLanguageModel

from neos.config.model_config import models_for_provider
from neos.config.settings import settings
from .base import ModelProviderBase


class OpenAIProvider(ModelProviderBase):
    """OpenAI GPT API 프로바이더."""

    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")

    def get_provider_name(self) -> str:
        return "openai"

    def list_models(self) -> List[str]:
        return models_for_provider("openai")

    def validate_config(self) -> bool:
        return bool(settings.OPENAI_API_KEY)

    def create_llm(
        self,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> BaseLanguageModel:
        params: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "api_key": settings.OPENAI_API_KEY,
            "max_retries": 3,
            "request_timeout": settings.LLM_TIMEOUT,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        params.update(kwargs)
        return ChatOpenAI(**params)
