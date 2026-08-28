import re
from pathlib import Path


def _creates_table(sql: str, name: str) -> bool:
    """045 가 그 테이블을 만드는가.

    `IF NOT EXISTS` 를 선택적으로 받는 이유: 이 단언의 의도는 "045 가 이 세
    테이블을 만든다" 이지 정확한 철자가 아니다. 2026-08-28 에 재적용 멱등성을
    위해 `IF NOT EXISTS` 를 넣자(SCHEMA3) 문자열 비교가 깨졌는데, **바뀐 것은
    계약이 아니라 서식**이었다.
    """
    return re.search(rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?{re.escape(name)}\b", sql) is not None


def test_migration_045_has_single_current_generation_and_cleanup_ledger() -> None:
    sql = Path("db/migrations/045_add_coding_managed_sandboxes.sql").read_text()

    assert _creates_table(sql, "coding_sandbox_admissions")
    assert _creates_table(sql, "coding_managed_sandboxes")
    assert _creates_table(sql, "coding_sandbox_cleanup_attempts")
    assert "idx_coding_managed_sandboxes_current_task" in sql
    assert "WHERE cleaned_at IS NULL" in sql
    assert "CHECK (state = 'cleaned' OR cleaned_at IS NULL)" in sql
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
