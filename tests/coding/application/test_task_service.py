from datetime import UTC, datetime

import pytest

from neos.coding.application.task_service import (
    InMemoryCodingTaskRepository,
    CodingTaskService,
)
from neos.coding.domain.models import CodingTaskStatus
from neos.coding.events.store import InMemoryCodingEventStore

pytestmark = pytest.mark.no_db


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


async def test_task_service_notifies_only_after_event_commit() -> None:
    calls: list[str] = []
    events = InMemoryCodingEventStore()
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), events, clock=lambda: NOW
    )
    service.set_task_created_notifier(calls.append)

    task = await service.create_task(owner_id="u1", prompt="Fix it")

    assert calls == [task.task_id]
    assert (await events.list_after(task.task_id))[0].type == "task.created"


async def test_task_service_ignores_notifier_failure_after_persistence() -> None:
    tasks = InMemoryCodingTaskRepository()
    service = CodingTaskService(
        tasks, InMemoryCodingEventStore(), clock=lambda: NOW
    )

    def fail_notification(task_id: str) -> None:
        raise RuntimeError("wake failed")

    service.set_task_created_notifier(fail_notification)

    task = await service.create_task(owner_id="u1", prompt="Fix it")

    assert await tasks.get(task.task_id) == task


async def test_list_owned_is_owner_scoped_and_clamped() -> None:
    service = CodingTaskService(
        InMemoryCodingTaskRepository(),
        InMemoryCodingEventStore(),
        clock=lambda: NOW,
    )
    for index in range(3):
        await service.create_task(
            owner_id="u1", prompt=f"Mine {index}", task_id=f"ct_mine_{index}"
        )
    await service.create_task(owner_id="u2", prompt="Theirs", task_id="ct_theirs")

    owned = await service.list_owned("u1", limit=2)
    empty = await service.list_owned("missing", limit=20)
    clamped = await service.list_owned("u1", limit=0)

    assert [task.task_id for task in owned] == ["ct_mine_2", "ct_mine_1"]
    assert empty == []
    assert [task.task_id for task in clamped] == ["ct_mine_2"]


async def test_list_owned_omits_deleted_and_orders_by_activity() -> None:
    repo = InMemoryCodingTaskRepository()
    service = CodingTaskService(repo, InMemoryCodingEventStore(), clock=lambda: NOW)
    await service.create_task(owner_id="u1", prompt="Older", task_id="ct_old")
    await service.create_task(owner_id="u1", prompt="Newer", task_id="ct_new")
    await service.create_task(owner_id="u1", prompt="Gone", task_id="ct_gone")
    repo.record_activity("ct_old", datetime(2026, 7, 20, tzinfo=UTC))
    repo.record_activity("ct_new", datetime(2026, 7, 21, tzinfo=UTC))
    repo.record_activity("ct_gone", datetime(2026, 7, 22, tzinfo=UTC))
    repo.mark_deleted("ct_gone")

    tasks = await service.list_owned("u1", limit=20)

    assert [task.task_id for task in tasks] == ["ct_new", "ct_old"]
    assert all(task.prompt != "Gone" for task in tasks)
