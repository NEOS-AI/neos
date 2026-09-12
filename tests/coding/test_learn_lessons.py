from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from neos.coding.application.run_service import CodingRunService
from neos.coding.application.task_service import InMemoryCodingTaskRepository
from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.learn_lessons import approved_lesson_texts, stage_coding_lesson
from neos.coding.loop.base import LoopInput
from neos.learn.lessons import (
    LessonStatus,
    approved_texts,
    new_lesson,
    reset_lesson_store,
)
from neos.learn.policy import namespace
from tests.coding.fakes import InMemoryCodingRunRepository

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]


class RecordingLoop:
    def __init__(self) -> None:
        self.inputs: list[LoopInput] = []

    async def run(self, input, checkpoint, deps):
        self.inputs.append(input)
        if False:
            yield None


@pytest.mark.asyncio
async def test_stage_coding_lesson_is_noop_when_disabled() -> None:
    store = reset_lesson_store()
    assert (
        await stage_coding_lesson(
            owner_id="u1",
            task_id="ct_1",
            outcome="failed",
            events=[{"event_type": "run.failed", "error_code": "tool_denied"}],
        )
        is None
    )
    assert store.list() == ()


@pytest.mark.asyncio
async def test_staged_lesson_is_excluded_until_approved(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    owner_id = "u1"
    task_id = "ct_1"
    lesson = await stage_coding_lesson(
        owner_id=owner_id,
        task_id=task_id,
        outcome="failed",
        events=[{"event_type": "run.failed", "error_code": "tool_denied"}],
    )
    assert lesson is not None
    assert lesson.status is LessonStatus.STAGED
    ns = namespace(owner_id)
    assert approved_texts(store, ns) == ()
    assert await approved_lesson_texts(owner_id) == ()
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    assert approved_texts(store, ns) == (lesson.body,)
    assert await approved_lesson_texts(owner_id) == (lesson.body,)


@pytest.mark.asyncio
async def test_approved_lesson_texts_are_owner_scoped(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    lesson = await stage_coding_lesson(
        owner_id="u1",
        task_id="ct_1",
        outcome="failed",
        events=[{"event_type": "run.failed", "error_code": "tool_denied"}],
    )
    assert lesson is not None
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    assert await approved_lesson_texts("u1") == (lesson.body,)
    assert await approved_lesson_texts("u2") == ()
    assert await approved_lesson_texts(None) == ()
    assert await approved_lesson_texts("  ") == ()


@pytest.mark.asyncio
async def test_approved_lesson_texts_empty_when_flag_off(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", False)
    store = reset_lesson_store()
    lesson = store.add(new_lesson(namespace="owner:u1", title="t", body="hidden"))
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    assert await approved_lesson_texts("u1") == ()


@pytest.mark.asyncio
async def test_advance_one_safe_point_passes_task_owner_id() -> None:
    reset_lesson_store()
    tasks = InMemoryCodingTaskRepository()
    await tasks.create(
        CodingTask(
            task_id="ct_1",
            owner_id="u1",
            prompt="Fix it",
            status=CodingTaskStatus.QUEUED,
            version=1,
            last_seq=0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository = InMemoryCodingRunRepository(
        active_run=CodingRun(
            run_id="cr_1",
            task_id="ct_1",
            attempt=1,
            status=CodingRunStatus.RUNNING,
            resume_from_checkpoint_id=None,
            started_at=NOW,
        ),
        task_prompts={"ct_1": "Fix it"},
    )
    repository.task_statuses["ct_1"] = "running"
    loop = RecordingLoop()
    service = CodingRunService(
        tasks=tasks,
        runs=repository,
        events=InMemoryCodingEventStore(),
        interrupter=object(),
        loop=loop,
        clock=lambda: NOW,
    )

    await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")

    assert loop.inputs[0].owner_id == "u1"


def test_runtime_does_not_bake_owner_lessons_at_construction() -> None:
    source = (REPO_ROOT / "neos" / "coding" / "runtime.py").read_text(
        encoding="utf-8"
    )
    assert "owner = None" not in source
    assert "approved_texts(" not in source
    assert "get_lesson_store" not in source


@pytest.mark.asyncio
async def test_approved_lesson_texts_cap_at_five(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    for index in range(6):
        lesson = store.add(
            new_lesson(
                namespace="owner:u1",
                title=f"t{index}",
                body=f"lesson-body-{index}",
            )
        )
        store.update(replace(lesson, status=LessonStatus.APPROVED))
    texts = await approved_lesson_texts("u1")
    assert len(texts) == 5
    assert all("lesson-body-" in text for text in texts)
    assert sum(item.inject_count for item in store.list("owner:u1")) == 5


@pytest.mark.asyncio
async def test_approved_lesson_texts_mark_stale_after_seven_days(
    monkeypatch,
) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    old = store.add(
        new_lesson(
            namespace="owner:u1",
            title="old",
            body="old fact",
            now=datetime.now(UTC) - timedelta(days=8),
        )
    )
    fresh = store.add(
        new_lesson(
            namespace="owner:u1",
            title="fresh",
            body="fresh fact",
            now=datetime.now(UTC) - timedelta(days=2),
        )
    )
    store.update(replace(old, status=LessonStatus.APPROVED))
    store.update(replace(fresh, status=LessonStatus.APPROVED))
    texts = await approved_lesson_texts("u1")
    stale = next(text for text in texts if "old fact" in text)
    recent = next(text for text in texts if "fresh fact" in text)
    assert "may be stale" in stale
    assert "may be stale" not in recent


@pytest.mark.asyncio
async def test_approved_lesson_texts_fail_closed_on_store_error(
    monkeypatch,
) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    monkeypatch.setattr(
        "neos.coding.learn_lessons.resolve_lesson_session_factory",
        lambda: None,
    )

    def boom():
        raise RuntimeError("store down")

    monkeypatch.setattr("neos.coding.learn_lessons.get_lesson_store", boom)
    assert await approved_lesson_texts("u1") == ()
