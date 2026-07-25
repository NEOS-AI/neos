from pathlib import Path


MIGRATION = Path("db/migrations/044_add_coding_workspace_edits.sql")


def test_migration_044_has_idempotency_and_task_cleanup() -> None:
    sql = MIGRATION.read_text()

    assert "edit_id TEXT PRIMARY KEY" in sql
    assert "REFERENCES coding_tasks(task_id) ON DELETE CASCADE" in sql
    assert (
        "CHECK (status IN "
        "('prepared', 'committed', 'reconcile_required', 'applied'))"
    ) in sql
    assert "idx_coding_workspace_edits_pending" in sql


def test_migration_044_retains_metadata_but_not_file_content() -> None:
    sql = MIGRATION.read_text()

    assert "content_digest TEXT NOT NULL" in sql
    assert "content_bytes BIGINT NOT NULL" in sql
    assert "content TEXT" not in sql
    assert "ON DELETE CASCADE" in sql


def test_applied_checkpoint_reference_cannot_be_silently_cleared() -> None:
    sql = MIGRATION.read_text()

    assert "applied_checkpoint_id TEXT REFERENCES coding_checkpoints" in sql
    assert "ON DELETE SET NULL" not in sql
