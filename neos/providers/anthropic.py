"""AnthropicProvider — Anthropic Claude 모델 프로바이더

Phase 5 (OpenClaw ModelProvider 플러그인)
"""

import logging
from typing import Any, List

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseLanguageModel

from neos.config.settings import settings
from .base import ModelProviderBase

logger = logging.getLogger(__name__)


class AnthropicProvider(ModelProviderBase):
    """Anthropic Claude API 프로바이더.

    Thinking Blocks(extended thinking) 지원 포함.
    """

    def __init__(self):
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")

    def get_provider_name(self) -> str:
        return "anthropic"

    def list_models(self) -> List[str]:
        return [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
        ]

    def validate_config(self) -> bool:
        return bool(settings.ANTHROPIC_API_KEY)

    def create_llm(
        self,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> BaseLanguageModel:
        """ChatAnthropic 인스턴스 생성. Thinking Blocks 설정 처리 포함."""
        params: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "api_key": settings.ANTHROPIC_API_KEY,
            "max_retries": 3,
            "timeout": settings.LLM_TIMEOUT,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        params.update(kwargs)

        # Thinking Blocks 제어
        disable_thinking = params.pop("disable_thinking", False)
        if (settings.THINKING_BLOCKS_ENABLED or settings.MAX_THINKING_LENGTH > 0) and not disable_thinking:
            budget = settings.MAX_THINKING_LENGTH
            if budget < 1024:
                logger.warning("MAX_THINKING_LENGTH too low; raising to 1024")
                budget = 1024

            if params.get("temperature", 1.0) != 1.0:
                logger.warning(
                    "Thinking blocks require temperature=1.0; overriding %s → 1.0",
                    params.get("temperature"),
                )
                params["temperature"] = 1.0

            params["thinking"] = {"type": "enabled", "budget_tokens": budget}

            current_max = params.get("max_tokens", 0)
            if not current_max or current_max <= budget:
                params["max_tokens"] = budget + 4096
                logger.info("Set max_tokens=%d for thinking blocks", params["max_tokens"])

        return ChatAnthropic(**params)
