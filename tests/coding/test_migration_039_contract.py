from pathlib import Path


def test_migration_creates_durable_run_checkpoint_and_steering_tables() -> None:
    sql = Path("db/migrations/039_add_coding_runs_checkpoints.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS coding_checkpoints" in sql
    assert "CREATE TABLE IF NOT EXISTS coding_steering_requests" in sql
    assert "UNIQUE (task_id, phase_kind, attempt)" in sql
    assert "UNIQUE (task_id, tool_call_id)" in sql
    assert "loop_state_json JSONB NOT NULL" in sql
    assert "mode VARCHAR(32) NOT NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS checkpoint_id VARCHAR(64)" in sql
