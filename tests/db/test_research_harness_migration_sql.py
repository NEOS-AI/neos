from pathlib import Path


def test_research_harness_migration_contains_required_tables():
    sql = Path("db/migrations/032_add_research_harness_tables.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS research_harness_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS research_harness_check_results" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_research_harness_runs_session" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_research_harness_checks_run" in sql
