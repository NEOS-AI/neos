"""Staged / approved markdown lessons. No executable code."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from neos.learn.policy import write_approval_required

SessionFactory = Callable[[], Awaitable[Any]]


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
    last_injected_at: datetime | None = None
    inject_count: int = 0


class LessonStore(Protocol):
    def add(self, lesson: Lesson) -> Lesson: ...

    def get(self, lesson_id: str) -> Lesson | None: ...

    def list(self, namespace: str | None = None) -> tuple[Lesson, ...]: ...

    def update(self, lesson: Lesson) -> None: ...

    def record_inject(
        self, lesson_ids: Sequence[str], *, now: datetime | None = None
    ) -> None: ...


def force_stage_on_write(lesson: Lesson) -> Lesson:
    if write_approval_required() and lesson.status is LessonStatus.APPROVED:
        return replace(lesson, status=LessonStatus.STAGED)
    return lesson


class InMemoryLessonStore:
    def __init__(self) -> None:
        self._items: dict[str, Lesson] = {}

    def add(self, lesson: Lesson) -> Lesson:
        stored = force_stage_on_write(lesson)
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

    def record_inject(
        self, lesson_ids: Sequence[str], *, now: datetime | None = None
    ) -> None:
        injected_at = now or datetime.now(UTC)
        for lesson_id in lesson_ids:
            current = self._items.get(lesson_id)
            if current is None or current.status is not LessonStatus.APPROVED:
                continue
            self._items[lesson_id] = replace(
                current,
                last_injected_at=injected_at,
                inject_count=current.inject_count + 1,
            )


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
_SESSION_FACTORY: SessionFactory | None = None
_USE_MEMORY_ONLY = False


def set_lesson_session_factory(factory: SessionFactory | None) -> None:
    global _SESSION_FACTORY, _USE_MEMORY_ONLY
    _SESSION_FACTORY = factory
    _USE_MEMORY_ONLY = factory is None


def resolve_lesson_session_factory() -> SessionFactory | None:
    if _USE_MEMORY_ONLY:
        return None
    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY
    try:
        from neos.database.connection import db_manager
    except Exception:
        return None
    if getattr(db_manager, "session_factory", None) is None:
        return None
    return db_manager.get_session


def get_lesson_store() -> InMemoryLessonStore:
    global _STORE
    if _STORE is None:
        _STORE = InMemoryLessonStore()
    return _STORE


def reset_lesson_store() -> InMemoryLessonStore:
    global _STORE, _SESSION_FACTORY, _USE_MEMORY_ONLY
    _STORE = InMemoryLessonStore()
    _SESSION_FACTORY = None
    _USE_MEMORY_ONLY = True
    return _STORE
