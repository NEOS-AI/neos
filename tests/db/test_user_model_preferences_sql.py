from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "db" / "migrations" / "063_add_user_model_preferences.sql"


def test_migration_creates_the_table_idempotently() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS user_model_preferences" in sql
    assert "PRIMARY KEY (user_id, model_pin)" in sql
    assert "REFERENCES users(user_id) ON DELETE CASCADE" in sql


def test_bootstrap_order_includes_063() -> None:
    from scripts.verify_schema_bootstrap import bootstrap_order

    order = bootstrap_order()
    assert "db/migrations/063_add_user_model_preferences.sql" in order
