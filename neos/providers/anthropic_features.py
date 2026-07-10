from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from neos.config.schema import AdvisorConfig, PromptCachingConfig

ADVISOR_BETA = "advisor-tool-2026-03-01"

_MODEL_PREFIXES = (
    ("claude-haiku-4-5", "haiku-4.5"),
    ("claude-sonnet-4-5", "sonnet-4.5"),
    ("claude-sonnet-4-6", "sonnet-4.6"),
    ("claude-sonnet-5", "sonnet-5"),
    ("claude-opus-4-6", "opus-4.6"),
    ("claude-opus-4-7", "opus-4.7"),
    ("claude-opus-4-8", "opus-4.8"),
    ("claude-fable-5", "fable-5"),
    ("claude-mythos-5", "mythos-5"),
)

_ADVISOR_COMPATIBILITY = {
    "haiku-4.5": {
        "sonnet-4.6",
        "opus-4.6",
        "opus-4.7",
        "opus-4.8",
        "fable-5",
        "mythos-5",
    },
    "sonnet-4.6": {
        "sonnet-4.6",
        "opus-4.6",
        "opus-4.7",
        "opus-4.8",
        "fable-5",
        "mythos-5",
    },
    "sonnet-5": {"opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "opus-4.6": {"opus-4.6", "opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "opus-4.7": {"opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "opus-4.8": {"opus-4.7", "opus-4.8", "fable-5", "mythos-5"},
    "fable-5": {"fable-5"},
    "mythos-5": {"mythos-5"},
}


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
    normalized = model.lower()
    for prefix, family in _MODEL_PREFIXES:
        if normalized.startswith(prefix):
            return family
    return None


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
        elif advisor_family is None or advisor_family not in _ADVISOR_COMPATIBILITY.get(
            executor_family, set()
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
