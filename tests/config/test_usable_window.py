"""G1 catalog usable window math."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from neos.config.model_config import ModelCatalog, load_catalog
from neos.config.model_identity import (
    catalog_window_for,
    reserved_tokens,
    usable_window_for,
    usable_window_tokens,
)

pytestmark = pytest.mark.no_db


def test_reserved_tokens_are_min_of_cap_and_ten_percent() -> None:
    assert reserved_tokens(200_000) == 20_000
    assert reserved_tokens(100_000) == 10_000
    assert reserved_tokens(50_000) == 5_000
    assert reserved_tokens(0) == 0


def test_usable_uses_input_limit_when_present() -> None:
    # reserved = min(20000, 10% of 200k window) = 20000
    assert (
        usable_window_tokens(
            context_window=200_000,
            max_output_tokens=8_192,
            input_limit=180_000,
            thinking_budget=1_024,
        )
        == 180_000 - 20_000 - 1_024
    )


def test_usable_subtracts_max_output_when_input_limit_absent() -> None:
    assert (
        usable_window_tokens(
            context_window=200_000,
            max_output_tokens=8_192,
            thinking_budget=0,
        )
        == 200_000 - 8_192 - 20_000
    )


def test_usable_clamps_at_zero() -> None:
    assert (
        usable_window_tokens(
            context_window=8_000,
            max_output_tokens=8_192,
            thinking_budget=20_000,
        )
        == 0
    )


def test_unknown_model_has_no_usable_window() -> None:
    catalog = ModelCatalog.model_validate({"models": {}})
    assert (
        usable_window_for(
            "claude-from-the-future",
            catalog=catalog,
            max_output_tokens=8192,
        )
        is None
    )
    window = catalog_window_for(
        "claude-from-the-future",
        catalog=catalog,
        max_output_tokens=8192,
    )
    assert window.context_window is None
    assert window.usable is None


def test_catalog_window_reads_yaml_fields(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "claude-x": {
                        "provider": "anthropic",
                        "context_window": 200000,
                        "input_limit": 180000,
                        "max_tokens": 8192,
                        "thinking_budgets": {"default": 1024, "max": 32000},
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    catalog = load_catalog(path)
    spec = catalog.models["claude-x"]
    assert spec.context_window == 200_000
    assert spec.input_limit == 180_000
    assert spec.thinking_budgets["default"] == 1_024
    assert (
        usable_window_for("claude-x", catalog=catalog, max_output_tokens=8192)
        == 180_000 - 20_000 - 1_024
    )


def test_catalog_rejects_negative_thinking_budget(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "claude-x": {
                        "provider": "anthropic",
                        "thinking_budgets": {"default": -1},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="thinking_budgets"):
        load_catalog(path)


def test_committed_sonnet5_usable_replaces_80k_constant() -> None:
    catalog = load_catalog(Path("neos/config/models.yaml"))
    usable = usable_window_for(
        "claude-sonnet-5",
        catalog=catalog,
        max_output_tokens=8192,
    )
    assert usable is not None
    assert usable > 80_000
    spec = catalog.models["claude-sonnet-5"]
    assert spec.context_window == 200_000
