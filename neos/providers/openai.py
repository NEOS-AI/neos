"""OpenAIProvider — OpenAI GPT 모델 프로바이더

Phase 5 (OpenClaw ModelProvider 플러그인)
"""

from typing import Any, List

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLanguageModel

from neos.config.model_config import models_for_provider
from neos.config.settings import settings
from .base import CodingCapabilities, ModelProviderBase
from .effort import effort_request_fields


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
        effort = params.pop("effort", None)
        params.update(effort_request_fields("openai", effort))
        return ChatOpenAI(**params)

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
        from neos.coding.model.openai import OpenAICodingModel
        from neos.utils.openai_client import build_async_openai

        return OpenAICodingModel(
            build_async_openai(api_key=api_key, base_url=base_url, **kwargs),
            max_tool_input_bytes=max_tool_input_bytes,
            max_tool_input_depth=max_tool_input_depth,
        )
