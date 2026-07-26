"""AnthropicProvider — Anthropic Claude 모델 프로바이더

Phase 5 (OpenClaw ModelProvider 플러그인)
"""

import logging
from typing import Any, List

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseLanguageModel

from neos.config.model_config import (
    ThinkingContract,
    models_for_provider,
    thinking_contract,
)
from neos.config.settings import settings
from .base import ModelProviderBase

logger = logging.getLogger(__name__)


def normalize_anthropic_request(
    model: str,
    params: dict[str, Any],
    *,
    thinking_enabled: bool,
) -> dict[str, Any]:
    """adaptive thinking 계약을 쓰는 모델의 요청을 정규화한다.

    계약은 모델 카탈로그(`neos/config/models.yaml`)가 선언한다.
    """
    normalized = dict(params)
    if thinking_contract(model) is not ThinkingContract.ADAPTIVE:
        return normalized

    thinking = normalized.get("thinking")
    if isinstance(thinking, dict) and "budget_tokens" in thinking:
        raise ValueError(
            "budget_tokens is not supported by the adaptive thinking contract"
        )

    normalized.pop("temperature", None)
    normalized.pop("top_p", None)
    normalized.pop("top_k", None)
    normalized["thinking"] = (
        {"type": "adaptive"} if thinking_enabled else {"type": "disabled"}
    )
    return normalized


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
        return models_for_provider("anthropic")

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

        # Thinking Blocks 제어 — 계약은 카탈로그가 선언한다
        disable_thinking = params.pop("disable_thinking", False)
        contract = thinking_contract(model)

        if contract is ThinkingContract.ADAPTIVE:
            params = normalize_anthropic_request(
                model,
                params,
                thinking_enabled=not disable_thinking,
            )
        elif contract is ThinkingContract.BUDGETED and (
            (settings.THINKING_BLOCKS_ENABLED or settings.MAX_THINKING_LENGTH > 0)
            and not disable_thinking
        ):
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
