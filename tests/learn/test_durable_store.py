from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.learn.lessons import (
    LessonStatus,
    new_lesson,
    reset_lesson_store,
    resolve_lesson_session_factory,
    set_lesson_session_factory,
)
from neos.learn.postgres import PostgresLessonStore

pytestmark = pytest.mark.no_db


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


class _FakeBegin:
    async def __aenter__(self) -> "_FakeBegin":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeLessonSession:
    def __init__(self, rows: dict[str, dict]) -> None:
        self._rows = rows

    async def __aenter__(self) -> "FakeLessonSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def begin(self) -> _FakeBegin:
        return _FakeBegin()

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        values = dict(params or {})
        if "insert into learned_lessons" in sql:
            self._rows[values["lesson_id"]] = values
            return _FakeResult([])
        if "update learned_lessons" in sql:
            current = self._rows.get(values["lesson_id"])
            if current is not None:
                current.update(values)
            return _FakeResult([])
        if "where lesson_id" in sql:
            row = self._rows.get(values["lesson_id"])
            return _FakeResult([row] if row is not None else [])
        if "where namespace" in sql:
            matched = [
                row
                for row in self._rows.values()
                if row["namespace"] == values["namespace"]
            ]
            if "status" in values:
                matched = [row for row in matched if row["status"] == values["status"]]
            return _FakeResult(matched)
        return _FakeResult(list(self._rows.values()))


def _factory(rows: dict[str, dict]):
    async def factory() -> FakeLessonSession:
        return FakeLessonSession(rows)

    return factory


@pytest.mark.asyncio
async def test_durable_store_is_readable_from_a_new_instance() -> None:
    backend: dict[str, dict] = {}
    first = PostgresLessonStore(_factory(backend))
    created = await first.add(
        new_lesson(
            namespace="owner:u1",
            title="rate-limit",
            body="The rate limit is 60.",
            now=datetime(2026, 9, 11, tzinfo=UTC),
        )
    )
    second = PostgresLessonStore(_factory(backend))
    loaded = await second.get(created.lesson_id)
    assert loaded is not None
    assert loaded.lesson_id == created.lesson_id
    assert loaded.body == "The rate limit is 60."
    assert loaded.status is LessonStatus.STAGED


@pytest.mark.asyncio
async def test_durable_add_force_stages_when_write_approval_is_on() -> None:
    backend: dict[str, dict] = {}
    store = PostgresLessonStore(_factory(backend))
    staged = new_lesson(namespace="owner:u1", title="t", body="fact")
    approved = replace(staged, status=LessonStatus.APPROVED)
    stored = await store.add(approved)
    assert stored.status is LessonStatus.STAGED
    loaded = await store.get(stored.lesson_id)
    assert loaded is not None
    assert loaded.status is LessonStatus.STAGED


def test_reset_prefers_in_memory_and_override_selects_session_factory() -> None:
    reset_lesson_store()
    assert resolve_lesson_session_factory() is None
    sentinel = object()
    set_lesson_session_factory(sentinel)  # type: ignore[arg-type]
    assert resolve_lesson_session_factory() is sentinel
    reset_lesson_store()
    assert resolve_lesson_session_factory() is None
