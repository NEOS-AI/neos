from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


def test_migration_creates_channel_coding_bindings() -> None:
    sql = Path("db/migrations/050_add_channel_coding_bindings.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS channel_coding_bindings" in sql
    assert "session_id VARCHAR(255) PRIMARY KEY" in sql
    assert "task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE" in sql
    assert "owner_id VARCHAR(255) NOT NULL" in sql
    assert "idx_channel_coding_bindings_task" in sql
    assert "ON channel_coding_bindings(task_id)" in sql
