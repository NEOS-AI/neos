from dataclasses import replace

import pytest

from neos.coding.learn_lessons import stage_coding_lesson
from neos.learn.lessons import LessonStatus, approved_texts, reset_lesson_store
from neos.learn.policy import namespace

pytestmark = pytest.mark.no_db


def test_stage_coding_lesson_is_noop_when_disabled() -> None:
    store = reset_lesson_store()
    assert (
        stage_coding_lesson(
            owner_id="u1",
            task_id="ct_1",
            outcome="failed",
            events=[{"event_type": "run.failed", "error_code": "tool_denied"}],
        )
        is None
    )
    assert store.list() == ()


def test_staged_lesson_is_excluded_until_approved(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    owner_id = "u1"
    task_id = "ct_1"
    lesson = stage_coding_lesson(
        owner_id=owner_id,
        task_id=task_id,
        outcome="failed",
        events=[{"event_type": "run.failed", "error_code": "tool_denied"}],
    )
    assert lesson is not None
    assert lesson.status is LessonStatus.STAGED
    ns = namespace(owner_id)
    assert approved_texts(store, ns) == ()
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    assert approved_texts(store, ns) == (lesson.body,)
