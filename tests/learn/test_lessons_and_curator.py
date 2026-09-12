from datetime import UTC, datetime, timedelta

import pytest

from neos.learn.curator import curate_lessons
from neos.learn.extract import extract_coding_lesson, extract_research_procedure
from neos.learn.lessons import (
    LessonStatus,
    approved_texts,
    get_lesson_store,
    new_lesson,
    reset_lesson_store,
)

pytestmark = pytest.mark.no_db


def test_new_lessons_are_staged_and_not_in_approved_texts() -> None:
    store = reset_lesson_store()
    lesson = store.add(
        new_lesson(namespace="owner:u1", title="t", body="The rate limit is 60.")
    )
    assert lesson.status is LessonStatus.STAGED
    assert approved_texts(store, "owner:u1") == ()


def test_coding_failure_extracts_a_lesson_success_does_not() -> None:
    failed = extract_coding_lesson(
        owner_id="u1",
        task_id="ct_1",
        outcome="failed",
        events=[{"event_type": "run.failed", "error_code": "precondition_read_required"}],
    )
    ok = extract_coding_lesson(
        owner_id="u1",
        task_id="ct_2",
        outcome="completed",
        events=[{"event_type": "run.completed"}],
    )
    assert failed is not None
    assert failed.status is LessonStatus.STAGED
    assert "precondition_read_required" in failed.body
    assert ok is None


def test_extractor_drops_env_and_unverified_failures() -> None:
    env = extract_coding_lesson(
        owner_id="u1",
        task_id="ct_env",
        outcome="failed",
        events=[{"event_type": "run.failed", "error_code": "sandbox_timeout"}],
    )
    unknown = extract_coding_lesson(
        owner_id="u1",
        task_id="ct_unk",
        outcome="failed",
        events=[{"event_type": "run.failed", "error_code": "tool_outcome_unknown"}],
    )
    assert env is None
    assert unknown is None


def test_research_procedure_is_document_only() -> None:
    lesson = extract_research_procedure(
        owner_id="u1",
        pipeline="pdf-html-gate",
        steps=("fetch pdf", "html gate", "cite", "write skill.py"),
    )
    assert "skill.py" not in lesson.body
    assert lesson.kind == "procedure"
    assert lesson.title == "pdf-html-gate"
    assert lesson.body.split("\n", 1)[0].__len__() <= 60


def test_curator_archives_stale_staged_but_skips_pin_and_builtin() -> None:
    store = reset_lesson_store()
    old = datetime(2020, 1, 1, tzinfo=UTC)
    store.add(
        new_lesson(namespace="owner:u1", title="old", body="fact", now=old)
    )
    store.add(
        new_lesson(
            namespace="owner:u1",
            title="pdf",
            body="bundled",
            now=old,
        )
    )
    store.add(
        new_lesson(
            namespace="owner:u1",
            title="pinned",
            body="keep",
            pinned=True,
            now=old,
        )
    )
    result = curate_lessons(store, now=datetime.now(UTC), stale_days=30)
    assert result["archived"] == 1
    assert store.list()[0].status is LessonStatus.ARCHIVED or any(
        item.title == "old" and item.status is LessonStatus.ARCHIVED
        for item in store.list()
    )
    assert any(
        item.title == "pdf" and item.status is not LessonStatus.ARCHIVED
        for item in store.list()
    )
    assert any(item.title == "pinned" and item.pinned for item in store.list())
