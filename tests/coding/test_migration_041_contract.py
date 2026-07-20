from pathlib import Path


def test_migration_creates_unique_task_binding_with_cas_version() -> None:
    sql = Path("db/migrations/041_add_coding_sandbox_bindings.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_sandbox_bindings" in sql
    assert "UNIQUE (task_id)" in sql
    assert "version BIGINT NOT NULL" in sql
    assert "latest_snapshot_id" in sql
