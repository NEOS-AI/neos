from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.coding.application.task_service import (
    InMemoryCodingTaskRepository,
    CodingTaskService,
)
from neos.coding.domain.errors import InvalidTaskTransition
from neos.coding.domain.models import CodingTaskStatus
from neos.coding.events.store import InMemoryCodingEventStore
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.store import CheckpointWrite, SubagentNotFound
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    SubagentStatus,
    SubagentTicket,
)

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


def _child_ticket(parent_id: str, tool_call_id: str) -> SubagentTicket:
    return SubagentTicket(
        parent_kind=ParentKind.CODING,
        parent_id=parent_id,
        parent_run_id="cr_parent",
        parent_tool_call_id=tool_call_id,
        spec="explore",
        briefing=ParentBriefing(goal="inspect auth"),
        model=ModelPin(provider="anthropic", model="claude-test"),
    )


async def test_archive_deletes_only_that_parent_subagent_runs() -> None:
    store = InMemorySubagentStore()
    repo = InMemoryCodingTaskRepository()
    service = CodingTaskService(
        repo, InMemoryCodingEventStore(), clock=lambda: NOW, subagents=store
    )
    await service.create_task(owner_id="u1", prompt="Keep", task_id="ct_keep")
    drop = await service.create_task(owner_id="u1", prompt="Drop", task_id="ct_drop")
    await repo.save(replace(drop, status=CodingTaskStatus.COMPLETED))
    victim = await store.resolve_or_create(_child_ticket("ct_drop", "toolu_1"))
    reserved = await store.reserve(victim.run_id, None)
    await store.commit(
        reserved,
        CheckpointWrite(
            loop_state={"messages": [{"role": "user", "content": "brief"}]},
            status=SubagentStatus.RUNNING,
            turn_count=1,
            tool_count=0,
        ),
    )
    kept = await store.resolve_or_create(_child_ticket("ct_keep", "toolu_1"))

    assert await service.archive("ct_drop", "u1") is True
    assert await service.archive("ct_drop", "u2") is False
    listed = await service.list_owned("u1", limit=20)
    assert [task.task_id for task in listed] == ["ct_keep"]
    with pytest.raises(SubagentNotFound):
        await store.get(victim.run_id)
    remaining = await store.get(kept.run_id)
    assert remaining.parent_id == "ct_keep"

    retried = await store.resolve_or_create(_child_ticket("ct_drop", "toolu_retry"))
    assert await service.archive("ct_drop", "u1") is True
    with pytest.raises(SubagentNotFound):
        await store.get(retried.run_id)
    assert (await store.get(kept.run_id)).parent_id == "ct_keep"


async def test_archive_refuses_non_terminal_tasks() -> None:
    store = InMemorySubagentStore()
    repo = InMemoryCodingTaskRepository()
    service = CodingTaskService(
        repo, InMemoryCodingEventStore(), clock=lambda: NOW, subagents=store
    )
    await service.create_task(owner_id="u1", prompt="Live", task_id="ct_live")
    child = await store.resolve_or_create(_child_ticket("ct_live", "toolu_1"))

    with pytest.raises(InvalidTaskTransition, match="queued.*archived"):
        await service.archive("ct_live", "u1")
    assert (await store.get(child.run_id)).parent_id == "ct_live"
    listed = await service.list_owned("u1", limit=20)
    assert [task.task_id for task in listed] == ["ct_live"]


async def _plant_child(store: InMemorySubagentStore, parent_id: str, tool_call_id: str):
    child = await store.resolve_or_create(_child_ticket(parent_id, tool_call_id))
    reserved = await store.reserve(child.run_id, None)
    await store.commit(
        reserved,
        CheckpointWrite(
            loop_state={"messages": [{"role": "user", "content": "brief"}]},
            status=SubagentStatus.RUNNING,
            turn_count=1,
            tool_count=0,
        ),
    )
    return child


async def test_hard_delete_removes_only_that_parent_subagent_runs() -> None:
    store = InMemorySubagentStore()
    repo = InMemoryCodingTaskRepository()
    service = CodingTaskService(
        repo, InMemoryCodingEventStore(), clock=lambda: NOW, subagents=store
    )
    await service.create_task(owner_id="u1", prompt="Keep", task_id="ct_keep")
    await service.create_task(owner_id="u1", prompt="Drop", task_id="ct_drop")
    victim = await _plant_child(store, "ct_drop", "toolu_1")
    kept = await store.resolve_or_create(_child_ticket("ct_keep", "toolu_1"))

    assert await service.delete("ct_drop", "u1") is True
    assert await service.delete("ct_drop", "u2") is False
    listed = await service.list_owned("u1", limit=20)
    assert [task.task_id for task in listed] == ["ct_keep"]
    assert await repo.get("ct_drop") is None
    with pytest.raises(SubagentNotFound):
        await store.get(victim.run_id)
    remaining = await store.get(kept.run_id)
    assert remaining.parent_id == "ct_keep"

    retried = await store.resolve_or_create(_child_ticket("ct_drop", "toolu_retry"))
    assert await service.delete("ct_drop", "u1") is False
    with pytest.raises(SubagentNotFound):
        await store.get(retried.run_id)
    assert (await store.get(kept.run_id)).parent_id == "ct_keep"


async def test_fail_without_archive_removes_parent_subagent_runs() -> None:
    store = InMemorySubagentStore()
    repo = InMemoryCodingTaskRepository()
    service = CodingTaskService(
        repo, InMemoryCodingEventStore(), clock=lambda: NOW, subagents=store
    )
    keep = await service.create_task(owner_id="u1", prompt="Keep", task_id="ct_keep")
    drop = await service.create_task(owner_id="u1", prompt="Drop", task_id="ct_drop")
    await repo.save(replace(drop, status=CodingTaskStatus.RUNNING))
    victim = await _plant_child(store, "ct_drop", "toolu_1")
    kept = await store.resolve_or_create(_child_ticket("ct_keep", "toolu_1"))

    assert await service.fail("ct_drop", "u1") is True
    assert await service.fail("ct_drop", "u2") is False
    failed = await repo.get("ct_drop")
    assert failed is not None
    assert failed.status is CodingTaskStatus.FAILED
    listed = await service.list_owned("u1", limit=20)
    assert {task.task_id for task in listed} == {"ct_keep", "ct_drop"}
    with pytest.raises(SubagentNotFound):
        await store.get(victim.run_id)
    remaining = await store.get(kept.run_id)
    assert remaining.parent_id == "ct_keep"
    assert keep.status is CodingTaskStatus.QUEUED

    retried = await store.resolve_or_create(_child_ticket("ct_drop", "toolu_retry"))
    assert await service.fail("ct_drop", "u1") is True
    with pytest.raises(SubagentNotFound):
        await store.get(retried.run_id)
    still = await repo.get("ct_drop")
    assert still is not None
    assert still.status is CodingTaskStatus.FAILED
    assert (await store.get(kept.run_id)).parent_id == "ct_keep"


async def test_fail_refuses_invalid_transition_and_keeps_children() -> None:
    store = InMemorySubagentStore()
    repo = InMemoryCodingTaskRepository()
    service = CodingTaskService(
        repo, InMemoryCodingEventStore(), clock=lambda: NOW, subagents=store
    )
    await service.create_task(owner_id="u1", prompt="Live", task_id="ct_live")
    child = await store.resolve_or_create(_child_ticket("ct_live", "toolu_1"))

    with pytest.raises(InvalidTaskTransition, match="queued.*failed"):
        await service.fail("ct_live", "u1")
    assert (await store.get(child.run_id)).parent_id == "ct_live"
    live = await repo.get("ct_live")
    assert live is not None
    assert live.status is CodingTaskStatus.QUEUED
