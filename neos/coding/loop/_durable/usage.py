"""Token and cost accounting against the loop's budgets.

Functions take `config` per call rather than capturing it, so pricing always
uses the loop's current config and never a copy taken earlier.
"""

from __future__ import annotations

from dataclasses import replace

from neos.coding.model.base import ModelCompleted
from neos.coding.loop._durable.codec import _nonneg_int
from neos.coding.loop._durable.state import AgentLoopState, CodingLoopFailure
from neos.config.model_identity import usable_window_tokens


def _usage_tokens(completion: ModelCompleted) -> tuple[int, int]:
    usage = completion.usage
    if usage is None:
        return 0, 0
    return usage.input_tokens, usage.output_tokens


def _usage_window(completion: ModelCompleted) -> tuple[int, int, int]:
    usage = completion.usage
    if usage is None:
        return 0, 0, 0
    return (
        _nonneg_int(getattr(usage, "cache_read_tokens", 0)),
        _nonneg_int(getattr(usage, "cache_write_tokens", 0)),
        _nonneg_int(getattr(usage, "reasoning_tokens", 0)),
    )


def price_tokens(
    config,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    return (
        input_tokens * config.input_cost_micros_per_million
        + output_tokens * config.output_cost_micros_per_million
        + cache_write_tokens * config.cache_write_cost_micros_per_million
        + cache_read_tokens * config.cache_read_cost_micros_per_million
    ) // 1_000_000


def with_turn_usage(
    config, state: AgentLoopState, completion: ModelCompleted
) -> AgentLoopState:
    """Charge one model turn to `state`. Every turn that commits goes through here."""
    in_tokens, out_tokens = _usage_tokens(completion)
    cache_read, cache_write, reasoning = _usage_window(completion)
    return replace(
        state,
        input_tokens=state.input_tokens + in_tokens,
        output_tokens=state.output_tokens + out_tokens,
        cache_read_tokens=state.cache_read_tokens + cache_read,
        cache_write_tokens=state.cache_write_tokens + cache_write,
        reasoning_tokens=state.reasoning_tokens + reasoning,
        cost_micros=state.cost_micros
        + price_tokens(
            config,
            in_tokens,
            out_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        ),
        last_prompt_tokens=in_tokens,
    )


def check_usage_budgets(config, state: AgentLoopState) -> None:
    # reasoning 은 output 안에 있다(`ModelUsage.reasoning_tokens`). 어댑터가
    # 그것을 늘 0 으로 읽던 동안에는 더해도 무해했다 -- 읽기를 고치자 두 번
    # 세게 됐다(2026-09-24).
    spent = (
        state.input_tokens
        + state.output_tokens
        + state.cache_read_tokens
        + state.cache_write_tokens
    )
    if spent > config.max_total_tokens:
        raise CodingLoopFailure("token_budget_exceeded", retryable=False)
    if state.cost_micros > config.max_cost_micros:
        raise CodingLoopFailure("cost_budget_exceeded", retryable=False)


def transcript_token_limit(config) -> int:
    """The maximum number of tokens that can be in a transcript.

    If a context window is configured, this is the usable window after
    reserving space for output. Otherwise, it uses the configured max.
    """
    usable = usable_window_tokens(
        context_window=config.context_window,
        max_output_tokens=config.max_output_tokens,
        input_limit=config.input_limit,
        thinking_budget=config.thinking_budget,
    )
    if usable is None:
        return config.max_transcript_tokens
    return usable


def parent_headroom_chars(config, state: AgentLoopState) -> int:
    """The number of characters available for a parent's prompt.

    Headroom is the remaining tokens multiplied by 4 (a conservative
    estimate of tokens per character), but never negative.
    """
    remaining = max(
        0, transcript_token_limit(config) - max(0, state.last_prompt_tokens)
    )
    return remaining * 4
