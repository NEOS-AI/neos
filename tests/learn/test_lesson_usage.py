from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from neos.coding.learn_lessons import approved_lesson_texts, coding_turn_system
from neos.learn.lessons import (
    LessonStatus,
    new_lesson,
    reset_lesson_store,
)
from neos.learn.postgres import PostgresLessonStore

from tests.learn.test_durable_store import _factory

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)


def _approve(store, *, owner_id: str, body: str):
    lesson = store.add(
        new_lesson(namespace=f"owner:{owner_id}", title="t", body=body)
    )
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    return loaded


def test_new_lesson_starts_with_zero_usage_metrics() -> None:
    lesson = new_lesson(namespace="owner:u1", title="t", body="The rate limit is 60.")
    assert lesson.inject_count == 0
    assert lesson.last_injected_at is None


def test_in_memory_record_inject_increments_count_and_timestamp() -> None:
    store = reset_lesson_store()
    lesson = _approve(store, owner_id="u1", body="The rate limit is 60.")

    store.record_inject((lesson.lesson_id,), now=FROZEN)

    updated = store.get(lesson.lesson_id)
    assert updated is not None
    assert updated.inject_count == 1
    assert updated.last_injected_at == FROZEN

    later = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
    store.record_inject((lesson.lesson_id,), now=later)
    again = store.get(lesson.lesson_id)
    assert again is not None
    assert again.inject_count == 2
    assert again.last_injected_at == later


def test_record_inject_skips_staged_and_unknown_ids() -> None:
    store = reset_lesson_store()
    staged = store.add(new_lesson(namespace="owner:u1", title="t", body="staged"))

    store.record_inject((staged.lesson_id, "ll_missing"), now=FROZEN)

    loaded = store.get(staged.lesson_id)
    assert loaded is not None
    assert loaded.inject_count == 0
    assert loaded.last_injected_at is None


@pytest.mark.asyncio
async def test_coding_turn_system_records_inject_on_approved_lesson(
    monkeypatch,
) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    lesson = _approve(store, owner_id="u1", body="Owner unique lesson body.")

    system = await coding_turn_system("static-system", "u1")

    assert "## Lessons" in system
    assert "Owner unique lesson body." in system
    updated = store.get(lesson.lesson_id)
    assert updated is not None
    assert updated.inject_count == 1
    assert updated.last_injected_at is not None
    assert updated.last_injected_at.tzinfo is UTC

    await coding_turn_system("static-system", "u1")
    again = store.get(lesson.lesson_id)
    assert again is not None
    assert again.inject_count == 2


@pytest.mark.asyncio
async def test_approved_lesson_texts_records_inject_for_returned_lessons(
    monkeypatch,
) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    lesson = _approve(store, owner_id="u1", body="Fetched for inject.")

    texts = await approved_lesson_texts("u1")

    assert texts == ("Fetched for inject.",)
    updated = store.get(lesson.lesson_id)
    assert updated is not None
    assert updated.inject_count == 1
    assert updated.last_injected_at is not None


@pytest.mark.asyncio
async def test_flag_off_does_not_record_inject(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", False)
    store = reset_lesson_store()
    lesson = _approve(store, owner_id="u1", body="Stay unused.")

    system = await coding_turn_system("static-system", "u1")
    texts = await approved_lesson_texts("u1")

    assert "## Lessons" not in system
    assert texts == ()
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    assert loaded.inject_count == 0
    assert loaded.last_injected_at is None


@pytest.mark.asyncio
async def test_staged_lesson_is_not_recorded_on_inject(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    lesson = store.add(
        new_lesson(namespace="owner:u1", title="t", body="Still staged.")
    )

    system = await coding_turn_system("static-system", "u1")

    assert "## Lessons" not in system
    loaded = store.get(lesson.lesson_id)
    assert loaded is not None
    assert loaded.inject_count == 0
    assert loaded.last_injected_at is None


@pytest.mark.asyncio
async def test_postgres_store_persists_and_increments_usage_metrics() -> None:
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
    await first.update(replace(created, status=LessonStatus.APPROVED))

    loaded = await first.get(created.lesson_id)
    assert loaded is not None
    assert loaded.inject_count == 0
    assert loaded.last_injected_at is None

    await first.record_inject((created.lesson_id,), now=FROZEN)
    second = PostgresLessonStore(_factory(backend))
    updated = await second.get(created.lesson_id)
    assert updated is not None
    assert updated.inject_count == 1
    assert updated.last_injected_at == FROZEN
    assert updated.status is LessonStatus.APPROVED


def test_migration_052_adds_nullable_usage_columns_not_claimed_by() -> None:
    path = REPO_ROOT / "db" / "migrations" / "052_add_lesson_usage_metrics.sql"
    sql = path.read_text(encoding="utf-8")

    assert "ALTER TABLE learned_lessons" in sql
    assert "ADD COLUMN IF NOT EXISTS last_injected_at TIMESTAMPTZ" in sql
    assert "ADD COLUMN IF NOT EXISTS inject_count" in sql
    assert "claimed_by" not in sql.lower()
    assert "NOT NULL" not in sql


def test_bootstrap_order_includes_052() -> None:
    # 정본 순서는 이제 BOOTSTRAP_ORDER.txt 의 규칙에서 **유도된다** (2026-09-20).
    # 파일 본문을 읽으면 번호순 자동 포함분이 안 보이므로 유도 결과를 본다.
    from scripts.verify_schema_bootstrap import bootstrap_order

    order = bootstrap_order()
    assert "db/migrations/052_add_lesson_usage_metrics.sql" in order
    assert order.index("db/migrations/051_allow_user_question_approvals.sql") < order.index(
        "db/migrations/052_add_lesson_usage_metrics.sql"
    )


def test_coding_lessons_stay_disabled_by_default() -> None:
    from neos.config.schema import AppConfig

    assert AppConfig().learn.coding_lessons is False
