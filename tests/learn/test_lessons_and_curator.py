from dataclasses import replace
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


def _approve(store, lesson):
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    return loaded


def test_curator_keeps_old_approved_lesson_that_was_recently_injected() -> None:
    store = reset_lesson_store()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    created = now - timedelta(days=120)
    lesson = _approve(
        store, store.add(new_lesson(namespace="owner:u1", title="used", body="keep", now=created))
    )
    store.record_inject((lesson.lesson_id,), now=now - timedelta(days=2))

    result = curate_lessons(store, now=now, stale_days=30, archive_days=90)

    assert result["archived"] == 0
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    assert loaded.status is LessonStatus.APPROVED
    assert loaded.inject_count == 1
    assert loaded.last_injected_at == now - timedelta(days=2)


def test_curator_archives_approved_lesson_idle_past_archive_days() -> None:
    store = reset_lesson_store()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    created = now - timedelta(days=200)
    lesson = _approve(
        store, store.add(new_lesson(namespace="owner:u1", title="idle", body="drop", now=created))
    )
    store.record_inject((lesson.lesson_id,), now=now - timedelta(days=100))

    result = curate_lessons(store, now=now, stale_days=30, archive_days=90)

    assert result["archived"] == 1
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    assert loaded.status is LessonStatus.ARCHIVED


def test_curator_does_not_archive_never_injected_lesson_younger_than_stale() -> None:
    store = reset_lesson_store()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    store.add(
        new_lesson(
            namespace="owner:u1",
            title="fresh",
            body="wait",
            now=now - timedelta(days=10),
        )
    )

    result = curate_lessons(store, now=now, stale_days=30, archive_days=90)

    assert result["archived"] == 0
    assert store.list()[0].status is LessonStatus.STAGED
    assert store.list()[0].inject_count == 0


def test_curator_archives_never_injected_staged_after_stale_days() -> None:
    store = reset_lesson_store()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    store.add(
        new_lesson(
            namespace="owner:u1",
            title="unused-staged",
            body="old staged",
            now=now - timedelta(days=40),
        )
    )

    result = curate_lessons(store, now=now, stale_days=30, archive_days=90)

    assert result["archived"] == 1
    assert store.list()[0].status is LessonStatus.ARCHIVED


def test_curator_archives_never_injected_approved_after_archive_days() -> None:
    store = reset_lesson_store()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    lesson = _approve(
        store,
        store.add(
            new_lesson(
                namespace="owner:u1",
                title="unused-approved",
                body="never used",
                now=now - timedelta(days=100),
            )
        ),
    )

    result = curate_lessons(store, now=now, stale_days=30, archive_days=90)

    assert result["archived"] == 1
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    assert loaded.status is LessonStatus.ARCHIVED
    assert loaded.inject_count == 0
