"""Deterministic prune/archive. No LLM consolidate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from neos.learn.lessons import Lesson, LessonStatus, LessonStore
from neos.learn.policy import is_protected_name


class AsyncLessonStore(Protocol):
    async def list(self, namespace: str | None = None) -> tuple[Lesson, ...]: ...

    async def update(self, lesson: Lesson) -> None: ...


def _activity_anchor(lesson: Lesson) -> datetime:
    stamp = lesson.last_injected_at or lesson.created_at
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=UTC)
    return stamp


def _never_used(lesson: Lesson) -> bool:
    return lesson.inject_count <= 0 and lesson.last_injected_at is None


def _should_archive(
    lesson: Lesson,
    *,
    stale_before: datetime,
    archive_before: datetime,
) -> bool:
    if lesson.status is LessonStatus.ARCHIVED:
        return False
    anchor = _activity_anchor(lesson)
    if _never_used(lesson) and anchor > stale_before:
        return False
    if anchor <= archive_before:
        return True
    return lesson.status is LessonStatus.STAGED and anchor <= stale_before


def _curation_updates(
    lessons: tuple[Lesson, ...],
    *,
    now: datetime,
    stale_days: int,
    archive_days: int,
) -> tuple[tuple[Lesson, ...], dict[str, int]]:
    stale_before = now - timedelta(days=stale_days)
    archive_before = now - timedelta(days=archive_days)
    archived = 0
    skipped = 0
    updates: list[Lesson] = []
    for lesson in lessons:
        if lesson.pinned or is_protected_name(lesson.title):
            skipped += 1
            continue
        if _should_archive(
            lesson, stale_before=stale_before, archive_before=archive_before
        ):
            updates.append(replace(lesson, status=LessonStatus.ARCHIVED))
            archived += 1
    return tuple(updates), {"archived": archived, "skipped": skipped}


def curate_lessons(
    store: LessonStore,
    *,
    now: datetime | None = None,
    stale_days: int = 30,
    archive_days: int = 90,
) -> dict[str, int]:
    updates, result = _curation_updates(
        store.list(),
        now=now or datetime.now(UTC),
        stale_days=stale_days,
        archive_days=archive_days,
    )
    for lesson in updates:
        store.update(lesson)
    return result


async def curate_lessons_async(
    store: AsyncLessonStore,
    *,
    now: datetime | None = None,
    stale_days: int = 30,
    archive_days: int = 90,
) -> dict[str, int]:
    updates, result = _curation_updates(
        await store.list(),
        now=now or datetime.now(UTC),
        stale_days=stale_days,
        archive_days=archive_days,
    )
    for lesson in updates:
        await store.update(lesson)
    return result

