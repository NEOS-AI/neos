from pathlib import Path


def test_migration_creates_coding_specific_approval_contract() -> None:
    sql = Path("db/migrations/042_add_coding_approvals.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_approvals" in sql
    assert "UNIQUE (task_id, run_id, tool_call_id)" in sql
    assert "normalized_input" not in sql
    assert "request_hash CHAR(64) NOT NULL" in sql
    assert "display_summary JSONB NOT NULL" in sql
    assert "expires_at > requested_at" in sql
    assert "idx_coding_approvals_pending_expiry" in sql
    assert "WHERE status = 'pending'" in sql


def test_migration_constrains_status_and_decision_columns() -> None:
    sql = Path("db/migrations/042_add_coding_approvals.sql").read_text()

    for status in ("pending", "approved", "denied", "expired", "invalidated"):
        assert f"'{status}'" in sql
    for decision in ("approve", "deny"):
        assert f"'{decision}'" in sql
    assert "decided_by" in sql
    assert "decided_at" in sql
