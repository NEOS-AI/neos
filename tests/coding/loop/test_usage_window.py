from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.loop import initial_state, parent_headroom_chars, transcript_token_limit, check_usage_budgets, price_tokens, estimated_tokens
from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelUsage,
    TextContent,
    TextDelta,
)
from tests.coding.loop.support import INPUT, collect, harness

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
    restored = h.restore(h.repository.checkpoints[-1])
    assert restored.input_tokens == 11
    assert restored.output_tokens == 5
    assert restored.cache_read_tokens == 8
    assert restored.cache_write_tokens == 3
    assert restored.reasoning_tokens == 4
    assert dumped["last_prompt_tokens"] == 11
    assert restored.last_prompt_tokens == 11


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
        initial_state(INPUT),
        input_tokens=10,
        output_tokens=10,
        cache_read_tokens=0,
        cache_write_tokens=0,
        reasoning_tokens=0,
    )

    check_usage_budgets(h.config, state)

    with pytest.raises(CodingLoopFailure) as caught:
        check_usage_budgets(
            h.config, replace(state, cache_read_tokens=6, cache_write_tokens=5)
        )
    assert caught.value.code == "token_budget_exceeded"

    # reasoning 은 output_tokens 의 내역이다 -- 더하면 thinking 을 두 번 센다.
    check_usage_budgets(h.config, replace(state, reasoning_tokens=10))


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
        price_tokens(
            h.config,
            1_000_000,
            1_000_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=1_000_000,
        )
        == 1_000_000 + 2_000_000 + 4_000_000 + 500_000
    )


@pytest.mark.asyncio
async def test_fold_child_passes_last_prompt_remainder() -> None:
    captured: dict[str, object] = {}

    class FoldSpy:
        async def fold(self, run_id, **kwargs):
            captured["run_id"] = run_id
            captured.update(kwargs)
            return "folded"

    h = harness(
        [[ModelCompleted("end_turn", ModelUsage(1, 1))]],
        config=AnthropicLoopConfig(
            model="claude-test",
            system="code",
            max_transcript_tokens=80_000,
            context_window=40_000,
            max_output_tokens=8_192,
        ),
        subagents=FoldSpy(),
    )
    usable = 40_000 - 8_192 - 4_000
    state = replace(
        initial_state(INPUT),
        last_prompt_tokens=usable - 200,
    )
    assert await h.loop._fold_child("sa_1", state) == "folded"
    assert captured["run_id"] == "sa_1"
    assert captured["parent_headroom_chars"] == 800
    assert captured["sibling_count"] == 1


def test_parent_headroom_chars_uses_last_prompt_remainder() -> None:
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
    usable = 40_000 - 8_192 - 4_000
    state = replace(
        initial_state(INPUT),
        last_prompt_tokens=usable - 200,
    )
    assert parent_headroom_chars(h.config, state) == 200 * 4
    empty = replace(state, last_prompt_tokens=0)
    assert parent_headroom_chars(h.config, empty) == usable * 4
    full = replace(state, last_prompt_tokens=usable + 10)
    assert parent_headroom_chars(h.config, full) == 0


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
    limit = transcript_token_limit(h.config)
    assert limit == 40_000 - 8_192 - 4_000
    short = (CanonicalMessage("user", (TextContent("x" * 100),)),)
    assert h.compactor().over_budget(short) is False
    mid = (CanonicalMessage("user", (TextContent("x" * (40_000 * 4)),)),)
    estimated = estimated_tokens(mid)
    assert estimated > limit
    assert estimated < 80_000
    assert h.compactor().over_budget(mid) is True


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
