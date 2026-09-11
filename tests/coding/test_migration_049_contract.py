from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


def test_migration_creates_learned_lessons_with_ns_status_index() -> None:
    sql = Path("db/migrations/049_add_learned_lessons.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS learned_lessons" in sql
    assert "lesson_id VARCHAR(64) PRIMARY KEY" in sql
    assert "namespace VARCHAR(255) NOT NULL" in sql
    assert "title VARCHAR(255) NOT NULL" in sql
    assert "body TEXT NOT NULL" in sql
    assert "status VARCHAR(32) NOT NULL" in sql
    assert "pinned BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "kind VARCHAR(32) NOT NULL DEFAULT 'fact'" in sql
    assert "created_at TIMESTAMPTZ NOT NULL" in sql
    assert "updated_at TIMESTAMPTZ NOT NULL" in sql
    assert "idx_learned_lessons_ns_status" in sql
    assert "ON learned_lessons(namespace, status)" in sql
