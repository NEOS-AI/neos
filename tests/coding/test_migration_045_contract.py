from pathlib import Path


def test_migration_045_has_single_current_generation_and_cleanup_ledger() -> None:
    sql = Path("db/migrations/045_add_coding_managed_sandboxes.sql").read_text()

    assert "CREATE TABLE coding_sandbox_admissions" in sql
    assert "CREATE TABLE coding_managed_sandboxes" in sql
    assert "CREATE TABLE coding_sandbox_cleanup_attempts" in sql
    assert "idx_coding_managed_sandboxes_current_task" in sql
    assert "WHERE cleaned_at IS NULL" in sql
    assert "provider_response" not in sql
    assert "prompt" not in sql
