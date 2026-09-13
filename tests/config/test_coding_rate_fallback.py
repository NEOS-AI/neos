"""G1: catalog prices fill cache rates and zero operator prices."""

from __future__ import annotations

import pytest

from neos.config.model_config import (
    ModelCatalog,
    resolve_coding_rate_micros,
)

pytestmark = pytest.mark.no_db


def _catalog() -> ModelCatalog:
    return ModelCatalog.model_validate(
        {
            "models": {
                "claude-x": {
                    "provider": "anthropic",
                    "pricing": {
                        "input": 3.0,
                        "output": 15.0,
                        "cache_creation": 3.75,
                        "cache_read": 0.30,
                    },
                }
            }
        }
    )


def test_zero_operator_prices_fall_back_to_catalog() -> None:
    rates = resolve_coding_rate_micros(
        provider="anthropic",
        model="claude-x",
        input_cost_micros_per_million=0,
        output_cost_micros_per_million=0,
        catalog=_catalog(),
    )
    assert rates.input == 3_000_000
    assert rates.output == 15_000_000
    assert rates.cache_write == 3_750_000
    assert rates.cache_read == 300_000


def test_operator_prices_win_and_catalog_fills_cache() -> None:
    rates = resolve_coding_rate_micros(
        provider="anthropic",
        model="claude-x",
        input_cost_micros_per_million=9_000_000,
        output_cost_micros_per_million=1,
        catalog=_catalog(),
    )
    assert rates.input == 9_000_000
    assert rates.output == 1
    assert rates.cache_write == 3_750_000
    assert rates.cache_read == 300_000


def test_unknown_model_keeps_operator_prices() -> None:
    rates = resolve_coding_rate_micros(
        provider="anthropic",
        model="claude-from-the-future",
        input_cost_micros_per_million=1,
        output_cost_micros_per_million=2,
        catalog=_catalog(),
    )
    assert rates.input == 1
    assert rates.output == 2
    assert rates.cache_write == 0
    assert rates.cache_read == 0
