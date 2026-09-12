from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
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


def test_usage_budget_uses_input_plus_output_not_cache() -> None:
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
        cache_read_tokens=1000,
        cache_write_tokens=1000,
        reasoning_tokens=1000,
    )

    h.loop._check_usage_budgets(state)

    with pytest.raises(CodingLoopFailure) as caught:
        h.loop._check_usage_budgets(replace(state, input_tokens=20, output_tokens=11))
    assert caught.value.code == "token_budget_exceeded"
