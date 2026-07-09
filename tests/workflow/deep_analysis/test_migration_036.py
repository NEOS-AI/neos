from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db

MIGRATION = Path("db/migrations/036_add_deep_analysis_tables.sql")


def test_migration_creates_run_scoped_harness_tables():
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "deep_analysis_runs",
        "deep_analysis_questions",
        "deep_analysis_claims",
        "deep_analysis_blobs",
        "deep_analysis_evidence",
        "deep_analysis_feedback",
        "deep_analysis_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "UNIQUE (run_id, hash)" in sql
    assert "PRIMARY KEY (run_id, content_hash)" in sql


def test_migration_preserves_run_scoped_referential_integrity():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert (
        "FOREIGN KEY (run_id, parent_id)"
        " REFERENCES deep_analysis_questions(run_id, id)"
    ) in " ".join(sql.split())
    assert (
        "FOREIGN KEY (run_id, question_id)"
        " REFERENCES deep_analysis_questions(run_id, id)"
    ) in " ".join(sql.split())
    assert (
        "FOREIGN KEY (run_id, claim_id)"
        " REFERENCES deep_analysis_claims(run_id, id)"
    ) in " ".join(sql.split())
    assert (
        "FOREIGN KEY (run_id, raw_ref)"
        " REFERENCES deep_analysis_blobs(run_id, content_hash)"
    ) in " ".join(sql.split())


def test_events_are_database_enforced_append_only():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "deep_analysis_events_reject_mutation" in sql
    assert "BEFORE UPDATE OR DELETE ON deep_analysis_events" in sql
    assert "deep_analysis_events is append-only" in sql
