from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.providers.anthropic_usage import (
    cache_minimum_tokens,
    calculate_anthropic_cost,
    normalize_anthropic_usage,
)


def test_normalize_usage_keeps_cache_categories_separate():
    usage = SimpleNamespace(
        input_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1000,
        output_tokens=25,
        iterations=[],
    )

    result = normalize_anthropic_usage(
        usage,
        model="claude-sonnet-4-6",
        cache_requested=True,
    )

    assert result["prompt_tokens"] == 50
    assert result["cache_creation_tokens"] == 0
    assert result["cache_read_tokens"] == 1000
    assert result["total_input_tokens"] == 1050
    assert result["total_tokens"] == 1075
    assert result["cache_status"] == "hit"


def test_normalize_usage_accepts_dicts_and_normalizes_iterations():
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "iterations": [
            {
                "type": "advisor_message",
                "model": "claude-opus-4-8",
                "input_tokens": 200,
                "cache_creation_input_tokens": 300,
                "cache_read_input_tokens": 400,
                "output_tokens": 40,
            }
        ],
    }

    result = normalize_anthropic_usage(
        usage,
        model="claude-sonnet-4-6",
        cache_requested=False,
    )

    assert result["cache_status"] == "disabled"
    assert result["iterations"] == [
        {
            "type": "advisor_message",
            "model": "claude-opus-4-8",
            "input_tokens": 200,
            "cache_creation_tokens": 300,
            "cache_read_tokens": 400,
            "output_tokens": 40,
        }
    ]


@pytest.mark.parametrize(
    ("model", "minimum"),
    [
        ("claude-sonnet-4-6", 1024),
        ("claude-opus-4-8", 1024),
        ("claude-opus-4-7", 2048),
        ("claude-opus-4-6", 4096),
        ("claude-haiku-4-5-20251001", 4096),
        ("claude-3-5-haiku-20241022", 2048),
    ],
)
def test_cache_minimum_tokens_uses_documented_model_thresholds(model, minimum):
    assert cache_minimum_tokens(model) == minimum


@pytest.mark.parametrize(
    ("usage", "cache_requested", "expected"),
    [
        ({"input_tokens": 100, "cache_read_input_tokens": 1}, True, "hit"),
        ({"input_tokens": 100, "cache_creation_input_tokens": 1}, True, "write"),
        ({"input_tokens": 100}, False, "disabled"),
        ({"input_tokens": 1023}, True, "ineligible"),
        ({"input_tokens": 1024}, True, "miss"),
    ],
)
def test_normalize_usage_classifies_cache_status(
    usage, cache_requested, expected
):
    result = normalize_anthropic_usage(
        usage,
        model="claude-sonnet-4-6",
        cache_requested=cache_requested,
    )

    assert result["cache_status"] == expected


@pytest.mark.asyncio
async def test_composite_cost_prices_executor_and_advisor_iterations():
    usage = SimpleNamespace(
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=500,
        output_tokens=20,
        iterations=[
            SimpleNamespace(
                type="message",
                input_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=500,
                output_tokens=20,
            ),
            SimpleNamespace(
                type="advisor_message",
                model="claude-opus-4-8",
                input_tokens=200,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                output_tokens=40,
            ),
        ],
    )

    def price_by_model(**kwargs):
        if kwargs["model_name"] == "claude-opus-4-8":
            return {"total_cost": Decimal("0.20")}
        return {"total_cost": Decimal("0.01")}

    calculator = AsyncMock(side_effect=price_by_model)

    result = await calculate_anthropic_cost(
        usage,
        executor_model="claude-sonnet-4-6",
        executor_cache_ttl="5m",
        advisor_cache_ttl="1h",
        calculator=calculator,
    )

    assert result["total_cost"] == Decimal("0.21")
    assert result["advisor_cost"] == Decimal("0.20")
    assert result["additional_cost"] == Decimal("0.20")
    assert result["advisor"] == {
        "call_count": 1,
        "models": ["claude-opus-4-8"],
        "input_tokens": 200,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 40,
        "error_codes": [],
    }
    assert calculator.await_count == 3
    assert calculator.await_args_list[1].kwargs["model_name"] == "claude-sonnet-4-6"
    assert calculator.await_args_list[1].kwargs["cache_ttl"] == "5m"
    assert calculator.await_args_list[2].kwargs["model_name"] == "claude-opus-4-8"
    assert calculator.await_args_list[2].kwargs["cache_ttl"] == "1h"


@pytest.mark.asyncio
async def test_cost_without_iterations_uses_top_level_base_once():
    calculator = AsyncMock(return_value={"total_cost": Decimal("0.03")})

    result = await calculate_anthropic_cost(
        {"input_tokens": 100, "output_tokens": 20},
        executor_model="claude-sonnet-4-6",
        executor_cache_ttl="5m",
        advisor_cache_ttl="5m",
        calculator=calculator,
    )

    assert result["total_cost"] == Decimal("0.03")
    assert result["additional_cost"] == Decimal("0")
    calculator.assert_awaited_once()
