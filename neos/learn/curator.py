"""Deterministic prune/archive. No LLM consolidate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from neos.learn.lessons import LessonStatus, LessonStore
from neos.learn.policy import is_protected_name


def curate_lessons(
    store: LessonStore,
    *,
    now: datetime | None = None,
    stale_days: int = 30,
    archive_days: int = 90,
) -> dict[str, int]:
    moment = now or datetime.now(UTC)
    stale_before = moment - timedelta(days=stale_days)
    archive_before = moment - timedelta(days=archive_days)
    archived = 0
    skipped = 0
    for lesson in store.list():
        if lesson.pinned or is_protected_name(lesson.title):
            skipped += 1
            continue
        if lesson.status is LessonStatus.ARCHIVED:
            continue
        if lesson.created_at <= archive_before or (
            lesson.status is LessonStatus.STAGED and lesson.created_at <= stale_before
        ):
            from dataclasses import replace

            store.update(replace(lesson, status=LessonStatus.ARCHIVED))
            archived += 1
    return {"archived": archived, "skipped": skipped}
