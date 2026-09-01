from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from neos.config.model_config import (
    advisor_targets as _advisor_targets,
    canonical_model_family as _canonical_model_family,
)
from neos.config.schema import AdvisorConfig, PromptCachingConfig

ADVISOR_BETA = "advisor-tool-2026-03-01"

# CA12: 세대 접두사 표와 advisor 호환표는 `neos/config/models.yaml` 의
# `anthropic_families:` 로 옮겼다. 여기 있던 시절 그 둘은 카탈로그가 갖지
# 않는 **둘째 모델 사실 테이블**이었고 -- 가격이 아니어서 병합 범위 밖에
# 있었다 -- 카탈로그 config화가 끝낸 드리프트를 다른 이름으로 되살렸다.
# 새 Claude 세대를 더할 때 이 파일은 손대지 않는다.


@dataclass(frozen=True)
class AdvisorDecision:
    requested: bool
    injected: bool
    skip_reason: str | None = None


@dataclass(frozen=True)
class AnthropicToolPolicy:
    tools: list[dict[str, Any]]
    betas: list[str]
    use_beta: bool
    advisor: AdvisorDecision


def build_cache_control(config: PromptCachingConfig) -> dict[str, str] | None:
    if not config.enabled:
        return None
    return {"type": "ephemeral", "ttl": config.ttl}


def canonical_model_family(model: str) -> str | None:
    """카탈로그가 아는 세대 이름. 모르면 `None`.

    이 저장소의 기존 호출부를 위해 이름을 남긴다 -- 구현만 카탈로그로
    옮겼고 계약(모르는 모델은 `None`)은 그대로다.
    """
    return _canonical_model_family(model)


def build_tool_policy(
    tools: Iterable[dict[str, Any]],
    *,
    executor_model: str,
    prompt_caching: PromptCachingConfig,
    advisor: AdvisorConfig,
) -> AnthropicToolPolicy:
    copied_tools = deepcopy(list(tools))
    decision = AdvisorDecision(requested=advisor.enabled, injected=False)
    betas: list[str] = []

    if advisor.enabled:
        executor_family = canonical_model_family(executor_model)
        advisor_family = canonical_model_family(advisor.model)
        if executor_family is None:
            decision = AdvisorDecision(True, False, "unknown_executor_model")
        elif advisor_family is None or advisor_family not in _advisor_targets(
            executor_family
        ):
            decision = AdvisorDecision(True, False, "incompatible_model_pair")
        else:
            advisor_tool: dict[str, Any] = {
                "type": "advisor_20260301",
                "name": "advisor",
                "model": advisor.model,
                "max_uses": advisor.max_uses,
                "max_tokens": advisor.max_tokens,
            }
            advisor_cache = build_cache_control(advisor.prompt_caching)
            if advisor_cache:
                advisor_tool["caching"] = advisor_cache
            copied_tools.append(advisor_tool)
            betas.append(ADVISOR_BETA)
            decision = AdvisorDecision(True, True)

    cache_control = build_cache_control(prompt_caching)
    if copied_tools and cache_control:
        copied_tools[-1]["cache_control"] = cache_control

    return AnthropicToolPolicy(
        tools=copied_tools,
        betas=betas,
        use_beta=decision.injected,
        advisor=decision,
    )


def serialize_content_block(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    if isinstance(block, dict):
        return deepcopy(block)
    raise TypeError(f"Unsupported Anthropic content block: {type(block).__name__}")
