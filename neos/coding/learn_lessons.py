"""Stage coding-run lessons. Opt-in; staged even when enabled."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from neos.config.settings import settings
from neos.learn.extract import extract_coding_lesson
from neos.learn.lessons import Lesson, get_lesson_store


def stage_coding_lesson(
    *,
    owner_id: str | None,
    task_id: str,
    outcome: str,
    events: Sequence[Mapping[str, object]] = (),
) -> Lesson | None:
    if not settings.config.learn.coding_lessons:
        return None
    lesson = extract_coding_lesson(
        owner_id=owner_id or "coding",
        task_id=task_id,
        outcome=outcome,
        events=events,
    )
    if lesson is None:
        return None
    return get_lesson_store().add(lesson)
