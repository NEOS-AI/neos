import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "db" / "chat_cost_tracking.sql"
MIGRATION = REPO / "db" / "migrations" / "056_llm_pricing_claude5.sql"
BOOTSTRAP = REPO / "db" / "BOOTSTRAP_ORDER.txt"

LEGACY_45 = (
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
    "claude-haiku-4-5-20251001",
)

# Catalog pins + models.yaml prices (USD / 1M). Keep in lockstep with
# neos/config/models.yaml; a stale DB row wins over the catalog.
CLAUDE5_PRICES = {
    "claude-sonnet-5": (3.00, 15.00, 3.75, 0.30),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 0.50),
}

_ROW = re.compile(
    r"\(\s*'anthropic'\s*,\s*'(?P<model>[^']+)'\s*,\s*"
    r"(?P<input>[\d.]+)\s*,\s*(?P<output>[\d.]+)\s*,\s*"
    r"(?P<cache_creation>[\d.]+)\s*,\s*(?P<cache_read>[\d.]+)"
)


def _rows(sql: str) -> dict[str, tuple[float, float, float, float]]:
    found: dict[str, tuple[float, float, float, float]] = {}
    for match in _ROW.finditer(sql):
        found[match.group("model")] = (
            float(match.group("input")),
            float(match.group("output")),
            float(match.group("cache_creation")),
            float(match.group("cache_read")),
        )
    return found


def test_seed_keeps_4_5_price_rows() -> None:
    sql = SEED.read_text(encoding="utf-8")
    rows = _rows(sql)
    for model in LEGACY_45:
        assert model in rows, f"4.5 row missing from seed: {model}"


def test_seed_adds_claude5_price_rows() -> None:
    sql = SEED.read_text(encoding="utf-8")
    rows = _rows(sql)
    for model, prices in CLAUDE5_PRICES.items():
        assert rows.get(model) == prices, f"seed {model}: {rows.get(model)} != {prices}"
    assert "ON CONFLICT (provider, model_name, effective_from) DO NOTHING" in sql


def test_migration_adds_claude5_prices_without_deleting_4_5() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    rows = _rows(sql)

    assert "INSERT INTO llm_model_pricing" in sql
    for model, prices in CLAUDE5_PRICES.items():
        assert rows.get(model) == prices, (
            f"migration {model}: {rows.get(model)} != {prices}"
        )

    # Unique key is (provider, model_name, effective_from). A bare INSERT
    # would duplicate pins on fresh bootstrap (seed then 056).
    assert "WHERE NOT EXISTS" in sql
    assert "existing.provider = v.provider" in sql
    assert "existing.model_name = v.model_name" in sql

    assert "delete from llm_model_pricing" not in sql.lower()
    for model in LEGACY_45:
        assert model not in rows


def test_bootstrap_order_includes_056_after_055() -> None:
    order = BOOTSTRAP.read_text(encoding="utf-8")
    assert "db/migrations/056_llm_pricing_claude5.sql" in order
    assert order.index("db/migrations/055_add_subagent_tables.sql") < order.index(
        "db/migrations/056_llm_pricing_claude5.sql"
    )
