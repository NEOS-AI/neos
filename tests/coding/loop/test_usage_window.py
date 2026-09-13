from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelUsage,
    TextContent,
    TextDelta,
)
from tests.coding.loop.test_anthropic_loop import INPUT, collect, harness

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_model_completed_usage_window_persists_on_state() -> None:
    usage = ModelUsage(
        input_tokens=11,
        output_tokens=5,
        cache_read_tokens=8,
        cache_write_tokens=3,
        reasoning_tokens=4,
    )
    h = harness([[TextDelta("done"), ModelCompleted("end_turn", usage)]])

    await collect(h)

    dumped = h.repository.checkpoints[-1].loop_state
    assert dumped["input_tokens"] == 11
    assert dumped["output_tokens"] == 5
    assert dumped["cache_read_tokens"] == 8
    assert dumped["cache_write_tokens"] == 3
    assert dumped["reasoning_tokens"] == 4
    restored = h.loop._restore(INPUT, h.repository.checkpoints[-1])
    assert restored.input_tokens == 11
    assert restored.output_tokens == 5
    assert restored.cache_read_tokens == 8
    assert restored.cache_write_tokens == 3
    assert restored.reasoning_tokens == 4


def test_usage_budget_counts_cache_and_reasoning() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            max_total_tokens=30,
        ),
    )
    state = replace(
        h.loop._restore(INPUT, None),
        input_tokens=10,
        output_tokens=10,
        cache_read_tokens=0,
        cache_write_tokens=0,
        reasoning_tokens=0,
    )

    h.loop._check_usage_budgets(state)

    with pytest.raises(CodingLoopFailure) as caught:
        h.loop._check_usage_budgets(
            replace(state, cache_read_tokens=6, cache_write_tokens=4, reasoning_tokens=1)
        )
    assert caught.value.code == "token_budget_exceeded"


def test_cost_prices_cache_from_config_rates() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            input_cost_micros_per_million=1_000_000,
            output_cost_micros_per_million=2_000_000,
            cache_write_cost_micros_per_million=4_000_000,
            cache_read_cost_micros_per_million=500_000,
        ),
    )
    # 1M tokens × rate_micros_per_million // 1M
    assert (
        h.loop._price_tokens(
            1_000_000,
            1_000_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=1_000_000,
        )
        == 1_000_000 + 2_000_000 + 4_000_000 + 500_000
    )


def test_compact_threshold_uses_usable_window_not_80k() -> None:
    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            max_transcript_tokens=80_000,
            context_window=40_000,
            max_output_tokens=8_192,
        ),
    )
    # usable = 40000 - 8192 - min(20000, 4000) = 27808
    limit = h.loop._transcript_token_limit()
    assert limit == 40_000 - 8_192 - 4_000
    short = (CanonicalMessage("user", (TextContent("x" * 100),)),)
    assert h.loop._over_budget(short) is False
    mid = (CanonicalMessage("user", (TextContent("x" * (40_000 * 4)),)),)
    estimated = h.loop._estimated_tokens(mid)
    assert estimated > limit
    assert estimated < 80_000
    assert h.loop._over_budget(mid) is True


@pytest.mark.asyncio
async def test_max_tokens_retry_prices_truncated_usage() -> None:
    h = harness(
        [
            [
                TextDelta("partial"),
                ModelCompleted(
                    "max_tokens",
                    ModelUsage(
                        input_tokens=10,
                        output_tokens=4,
                        cache_read_tokens=8,
                        cache_write_tokens=2,
                    ),
                ),
            ]
        ],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            input_cost_micros_per_million=1_000_000,
            output_cost_micros_per_million=2_000_000,
            cache_write_cost_micros_per_million=4_000_000,
            cache_read_cost_micros_per_million=500_000,
        ),
    )
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert state["output_token_escalations"] == 1
    assert state["input_tokens"] == 10
    assert state["output_tokens"] == 4
    assert state["cache_read_tokens"] == 8
    assert state["cache_write_tokens"] == 2
    assert state["cost_micros"] == 10 + 8 + 8 + 4
