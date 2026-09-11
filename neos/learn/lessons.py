"""Staged / approved markdown lessons. No executable code."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from neos.learn.policy import write_approval_required


class LessonStatus(StrEnum):
    STAGED = "staged"
    APPROVED = "approved"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Lesson:
    lesson_id: str
    namespace: str
    title: str
    body: str
    status: LessonStatus
    created_at: datetime
    pinned: bool = False
    kind: str = "fact"


class LessonStore(Protocol):
    def add(self, lesson: Lesson) -> Lesson: ...

    def get(self, lesson_id: str) -> Lesson | None: ...

    def list(self, namespace: str | None = None) -> tuple[Lesson, ...]: ...

    def update(self, lesson: Lesson) -> None: ...


class InMemoryLessonStore:
    def __init__(self) -> None:
        self._items: dict[str, Lesson] = {}

    def add(self, lesson: Lesson) -> Lesson:
        stored = lesson
        if write_approval_required() and stored.status is LessonStatus.APPROVED:
            stored = replace(stored, status=LessonStatus.STAGED)
        self._items[stored.lesson_id] = stored
        return stored

    def get(self, lesson_id: str) -> Lesson | None:
        return self._items.get(lesson_id)

    def list(self, namespace: str | None = None) -> tuple[Lesson, ...]:
        values = self._items.values()
        if namespace is None:
            return tuple(values)
        return tuple(item for item in values if item.namespace == namespace)

    def update(self, lesson: Lesson) -> None:
        self._items[lesson.lesson_id] = lesson


def new_lesson(
    *,
    namespace: str,
    title: str,
    body: str,
    kind: str = "fact",
    pinned: bool = False,
    now: datetime | None = None,
) -> Lesson:
    return Lesson(
        lesson_id=f"ll_{uuid4().hex}",
        namespace=namespace,
        title=title,
        body=body,
        status=LessonStatus.STAGED,
        created_at=now or datetime.now(UTC),
        pinned=pinned,
        kind=kind,
    )


def approved_texts(store: LessonStore, namespace: str) -> tuple[str, ...]:
    return tuple(
        item.body
        for item in store.list(namespace)
        if item.status is LessonStatus.APPROVED
    )


_STORE: InMemoryLessonStore | None = None


def get_lesson_store() -> InMemoryLessonStore:
    global _STORE
    if _STORE is None:
        _STORE = InMemoryLessonStore()
    return _STORE


def reset_lesson_store() -> InMemoryLessonStore:
    global _STORE
    _STORE = InMemoryLessonStore()
    return _STORE
