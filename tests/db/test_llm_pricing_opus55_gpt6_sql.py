import re
from pathlib import Path

import pytest

from neos.config.model_config import model_config

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "db" / "chat_cost_tracking.sql"
MIGRATION = REPO / "db" / "migrations" / "062_llm_pricing_opus55_gpt6.sql"

# 2026-09-24 replacements. llm_model_pricing outranks the catalog, so a DB
# row that drifts from models.yaml silently wins -- compare against the
# catalog itself instead of a second hand-written table.
PINS = ("claude-opus-5-5", "gpt-6-sol", "gpt-6-luna")

_ROW = re.compile(
    r"\(\s*'(?P<provider>anthropic|openai)'\s*,\s*'(?P<model>[^']+)'\s*,\s*"
    r"(?P<input>[\d.]+)\s*,\s*(?P<output>[\d.]+)\s*,\s*"
    r"(?P<cache_creation>[\d.]+)\s*,\s*(?P<cache_read>[\d.]+)"
)


def _rows(sql: str) -> dict[str, tuple[str, tuple[float, float, float, float]]]:
    return {
        m.group("model"): (
            m.group("provider"),
            (
                float(m.group("input")),
                float(m.group("output")),
                float(m.group("cache_creation")),
                float(m.group("cache_read")),
            ),
        )
        for m in _ROW.finditer(sql)
    }


def _catalog_row(pin: str) -> tuple[str, tuple[float, float, float, float]]:
    spec = model_config.catalog.models[pin]
    p = spec.pricing
    assert p is not None, f"{pin} has no catalog price"
    return spec.provider, (p.input, p.output, p.cache_creation, p.cache_read)


@pytest.mark.parametrize("path", [SEED, MIGRATION], ids=["seed", "migration"])
def test_new_pins_are_priced_like_the_catalog(path: Path) -> None:
    rows = _rows(path.read_text(encoding="utf-8"))
    for pin in PINS:
        assert rows.get(pin) == _catalog_row(pin), f"{path.name} {pin}"


def test_migration_is_idempotent_and_keeps_old_rows() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "WHERE NOT EXISTS" in sql
    assert "existing.model_name = v.model_name" in sql
    assert "delete from llm_model_pricing" not in sql.lower()


def test_bootstrap_order_includes_062() -> None:
    from scripts.verify_schema_bootstrap import bootstrap_order

    order = bootstrap_order()
    assert "db/migrations/062_llm_pricing_opus55_gpt6.sql" in order
    assert order.index("db/migrations/056_llm_pricing_claude5.sql") < order.index(
        "db/migrations/062_llm_pricing_opus55_gpt6.sql"
    )
