from pathlib import Path


def test_migration_creates_bounded_text_part_contract() -> None:
    sql = Path("db/migrations/043_add_coding_text_parts.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_text_parts" in sql
    assert "CHECK (status IN ('streaming', 'completed', 'interrupted'))" in sql
    assert "UNIQUE (task_id, turn_id)" in sql
    assert "content_bytes BIGINT NOT NULL" in sql
    assert "idx_coding_text_parts_task_first_seq" in sql
    assert "idx_coding_text_parts_task_status" in sql
