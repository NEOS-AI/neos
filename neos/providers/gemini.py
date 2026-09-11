"""GeminiProvider — Google Gemini 모델 프로바이더

Phase 5 (OpenClaw ModelProvider 플러그인)
"""

import logging
from typing import Any, List

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseLanguageModel

from neos.config.model_config import models_for_provider
from neos.config.settings import settings
from .base import CodingCapabilities, ModelProviderBase

logger = logging.getLogger(__name__)


class GeminiProvider(ModelProviderBase):
    """Google Gemini API 프로바이더."""

    def __init__(self):
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is required for Gemini provider")

    def get_provider_name(self) -> str:
        return "gemini"

    def list_models(self) -> List[str]:
        catalog = models_for_provider("gemini")
        if catalog:
            return catalog
        return [
            "gemini-2.0-flash-exp",
            "gemini-1.5-pro-latest",
            "gemini-2.5-flash-lite",
        ]

    def validate_config(self) -> bool:
        return bool(settings.GOOGLE_API_KEY)

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
            "google_api_key": settings.GOOGLE_API_KEY,
            "max_retries": 3,
            "timeout": settings.LLM_TIMEOUT,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        params.update(kwargs)
        return ChatGoogleGenerativeAI(**params)

    def coding_capabilities(self) -> CodingCapabilities:
        return CodingCapabilities(supported=True, streaming_tools=True)

    def create_coding_model(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tool_input_bytes: int = 65_536,
        max_tool_input_depth: int = 16,
        **kwargs: Any,
    ):
        from google import genai

        from neos.coding.model.gemini import GeminiCodingModel

        del base_url
        resolved = api_key or settings.GOOGLE_API_KEY
        return GeminiCodingModel(
            genai.Client(api_key=resolved, **kwargs),
            max_tool_input_bytes=max_tool_input_bytes,
            max_tool_input_depth=max_tool_input_depth,
        )
