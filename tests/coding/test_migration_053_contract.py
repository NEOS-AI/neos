from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


def test_migration_creates_channel_inbound_idempotency() -> None:
    sql = Path("db/migrations/053_add_channel_inbound_idempotency.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS channel_inbound_idempotency" in sql
    assert "session_id VARCHAR(255) NOT NULL" in sql
    assert "idempotency_key VARCHAR(255) NOT NULL" in sql
    assert "outcome TEXT NOT NULL" in sql
    assert "created_at TIMESTAMPTZ NOT NULL" in sql
    assert "PRIMARY KEY (session_id, idempotency_key)" in sql
    assert "REFERENCES coding_tasks" not in sql
