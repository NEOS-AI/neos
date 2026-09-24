"""AnthropicProvider — Anthropic Claude 모델 프로바이더

Phase 5 (OpenClaw ModelProvider 플러그인)
"""

import logging
from typing import Any, List

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseLanguageModel

from neos.config.model_config import (
    ThinkingContract,
    effort_levels_for,
    get_model_spec,
    models_for_provider,
    thinking_contract,
)
from neos.config.settings import settings
from neos.utils.anthropic_client import (
    anthropic_default_headers,
    build_async_anthropic,
)
from .base import CodingCapabilities, ModelProviderBase
from .effort import effort_request_fields

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
    if thinking_enabled:
        normalized["thinking"] = {"type": "adaptive"}
    elif _thinking_always_on(model):
        return _translate_thinking_off(model, normalized)
    else:
        normalized["thinking"] = {"type": "disabled"}
    return normalized


def _thinking_always_on(model: str) -> bool:
    spec = get_model_spec(model)
    return spec is not None and spec.thinking_always_on


def _translate_thinking_off(model: str, params: dict[str, Any]) -> dict[str, Any]:
    """끌 수 없는 모델에 온 "thinking 끄기" 요청을 400 이 아닌 형태로 번역한다.

    `{type: "disabled"}` 는 이 모델에서 모든 effort 에서 400 이다
    (claude-opus-5-5, claude-fable-5-1). 호출자(검색 에이전트의
    `DISABLE_THINKING_FOR_SEARCH`)가 원한 것은 "빠른 응답"이지 400 이 아니다.

    Anthropic 레퍼런스의 권고대로 thinking 을 켠 채 `effort: low` 로 번역한다
    -- 이 모델이 `low` 를 받는다고 **확인된** 경우에만. 명시적으로 정해진
    effort(사용자·설정)가 있으면 그것이 이긴다.
    """
    params["thinking"] = {"type": "adaptive"}
    if (params.get("output_config") or {}).get("effort"):
        return params
    if "low" in effort_levels_for(model):
        params["output_config"] = {
            **(params.get("output_config") or {}),
            "effort": "low",
        }
    return params


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
        spec = get_model_spec(model)
        wire_id = spec.wire_id if spec is not None and spec.wire_id else model
        params: dict[str, Any] = {
            "model": wire_id,
            "temperature": temperature,
            "api_key": settings.ANTHROPIC_API_KEY,
            "max_retries": 3,
            "timeout": settings.LLM_TIMEOUT,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        # identity-linked 키는 워크스페이스 헤더 없이 모든 요청이 400 이다.
        # `default_headers` 를 **빈 값일 때는 넣지 않는다** -- 빈 dict 를 넘기면
        # LangChain 이 그것을 SDK 로 전달하고, 그 경로가 지금과 같다는 보장이
        # 없다. 아무것도 안 하는 것이 지금과 같다는 유일한 보장이다.
        workspace_headers = anthropic_default_headers()
        if workspace_headers:
            params["default_headers"] = workspace_headers
        params.update(kwargs)
        effort = params.pop("effort", None)
        params.update(effort_request_fields("anthropic", effort))

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

    def coding_capabilities(self) -> CodingCapabilities:
        return CodingCapabilities(
            supported=True, streaming_tools=True, prompt_cache=True
        )

    def create_coding_model(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tool_input_bytes: int = 65_536,
        max_tool_input_depth: int = 16,
        **kwargs: Any,
    ):
        from neos.coding.model.anthropic import AnthropicCodingModel

        del base_url
        return AnthropicCodingModel(
            build_async_anthropic(api_key=api_key, **kwargs),
            max_tool_input_bytes=max_tool_input_bytes,
            max_tool_input_depth=max_tool_input_depth,
        )
