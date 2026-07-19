from pathlib import Path


def test_migration_adds_execution_and_claim_leases() -> None:
    sql = Path("db/migrations/040_add_coding_execution_leases.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_run_leases" in sql
    assert "fencing_token BIGINT NOT NULL" in sql
    assert "UNIQUE (task_id, run_id, fencing_token)" in sql
    assert "ADD COLUMN IF NOT EXISTS claimed_by" in sql
    assert "ADD COLUMN IF NOT EXISTS claim_expires_at" in sql
    assert "CHECK (status IN ('claimed', 'completed', 'failed'))" in sql
    assert "idx_coding_steering_claimable" in sql
