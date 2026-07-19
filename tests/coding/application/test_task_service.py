from datetime import UTC, datetime

from neos.coding.application.task_service import (
    InMemoryCodingTaskRepository,
    CodingTaskService,
)
from neos.coding.domain.models import CodingTaskStatus
from neos.coding.events.store import InMemoryCodingEventStore


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)


async def test_create_task_persists_created_event() -> None:
    tasks = InMemoryCodingTaskRepository()
    events = InMemoryCodingEventStore()
    service = CodingTaskService(tasks, events, clock=lambda: NOW)

    task = await service.create_task(
        owner_id="u1", prompt="Fix it", task_id="ct_fixed"
    )

    assert task.status is CodingTaskStatus.QUEUED
    assert task.last_seq == 1
    assert (await events.list_after(task.task_id))[0].type == "task.created"


async def test_snapshot_is_owner_scoped_and_contains_head_sequence() -> None:
    service = CodingTaskService(
        InMemoryCodingTaskRepository(),
        InMemoryCodingEventStore(),
        clock=lambda: NOW,
    )
    task = await service.create_task(owner_id="u1", prompt="Fix it")

    assert await service.snapshot(task.task_id, "u2") is None
    snapshot = await service.snapshot(task.task_id, "u1")
    assert snapshot is not None
    assert snapshot.head_seq == 1
    assert snapshot.task.task_id == task.task_id
