from pathlib import Path


def test_phase0_migration_enforces_ordered_owned_events() -> None:
    sql = Path("db/migrations/038_add_coding_phase0.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_tasks" in sql
    assert "CREATE TABLE IF NOT EXISTS coding_events" in sql
    assert "UNIQUE (task_id, seq)" in sql
    assert "REFERENCES users(user_id)" in sql
    assert "idx_coding_tasks_owner_activity" in sql
    assert "idx_coding_events_task_seq" in sql


def test_phase0_migration_creates_durable_event_outbox() -> None:
    sql = Path("db/migrations/038_add_coding_phase0.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_event_outbox" in sql
    assert "event_id VARCHAR(64) NOT NULL UNIQUE" in sql
    assert "REFERENCES coding_events(event_id)" in sql
    assert "idx_coding_outbox_eligible" in sql
    assert "WHERE published_at IS NULL" in sql
    assert "idx_coding_outbox_task_seq" in sql
