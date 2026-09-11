"""Stage coding-run lessons. Opt-in; staged even when enabled."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from neos.config.settings import settings
from neos.learn.extract import extract_coding_lesson
from neos.learn.lessons import (
    Lesson,
    approved_texts,
    get_lesson_store,
    resolve_lesson_session_factory,
)
from neos.learn.policy import namespace
from neos.learn.postgres import PostgresLessonStore


async def _persist_lesson(lesson: Lesson) -> Lesson:
    factory = resolve_lesson_session_factory()
    if factory is not None:
        return await PostgresLessonStore(factory).add(lesson)
    return get_lesson_store().add(lesson)


async def stage_coding_lesson(
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
    return await _persist_lesson(lesson)


async def approved_lesson_texts(owner_id: str | None) -> tuple[str, ...]:
    if not settings.config.learn.coding_lessons:
        return ()
    owner = (owner_id or "").strip()
    if not owner:
        return ()
    ns = namespace(owner)
    try:
        factory = resolve_lesson_session_factory()
        if factory is not None:
            return await PostgresLessonStore(factory).approved_texts(ns)
        return approved_texts(get_lesson_store(), ns)
    except Exception:
        return ()


async def coding_turn_system(static_system: str, owner_id: str | None) -> str:
    lessons = await approved_lesson_texts(owner_id)
    if not lessons:
        return static_system
    return f"{static_system}\n\n## Lessons\n" + "\n".join(lessons)

