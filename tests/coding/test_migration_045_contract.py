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


def test_migration_045_durably_links_and_settles_admission_reservations() -> None:
    sql = Path("db/migrations/045_add_coding_managed_sandboxes.sql").read_text()

    assert "UNIQUE (tenant_id, idempotency_key)" in sql
    assert "idempotency_key VARCHAR(128) NOT NULL UNIQUE" not in sql
    assert "admission_id VARCHAR(64) NOT NULL UNIQUE" in sql
    assert (
        "REFERENCES coding_sandbox_admissions(admission_id) ON DELETE RESTRICT"
        in sql
    )
    assert "reserved_active_seconds BIGINT NOT NULL" in sql
    assert "reserved_archive_bytes BIGINT NOT NULL" in sql
    assert "reserved_cost_micros BIGINT NOT NULL" in sql
    assert "reservation_state VARCHAR(16) NOT NULL" in sql
    assert "actual_active_seconds BIGINT NOT NULL" in sql
    assert "actual_archive_bytes BIGINT NOT NULL" in sql
    assert "actual_cost_micros BIGINT NOT NULL" in sql
    assert "reservation_settled_at TIMESTAMPTZ" in sql
    assert "reservation_released_at TIMESTAMPTZ" in sql
