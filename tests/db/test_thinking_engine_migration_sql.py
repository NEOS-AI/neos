from pathlib import Path


def test_thinking_engine_migration_defines_trace_and_dag_tables():
    sql = Path("db/migrations/033_add_thinking_engine_tables.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS thinking_engine_traces" in sql
    assert "CREATE TABLE IF NOT EXISTS thinking_engine_task_nodes" in sql
    assert "run_id VARCHAR(255)" in sql
    assert "artifact_ref TEXT" in sql
    assert "depends_on JSONB NOT NULL DEFAULT '[]'" in sql
    assert "idx_thinking_engine_task_nodes_status" in sql
