"""Q9c: `answer_user_question` keeps one contract in memory and in Postgres, and
`CodingRunService.resume_answered` reuses the Q10b resume path (design §7.3).

One transaction: the ask `answered`, `waiting_user -> running`, `question.answered`
and `task.status.changed{running, resumed_by: answer}` on the same run's latest
checkpoint. Only the task's owner answers, once; a task no longer waiting is not
answered and its ask stays `waiting`. Users are `test_q9_*`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from neos.coding.domain.phases import CodingRunStatus
from tests.standing.test_ask_repository import (
    OTHER,
    MemoryWorld,
    PostgresWorld,
    _ask,
    _seed_users,
)

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        world = MemoryWorld()
    else:
        await _seed_users()
        world = PostgresWorld()
    task_id, run_id, lease = await world.waiting_task()
    if request.param == "memory":
        world.runs.task_owners[task_id] = "test_q9_repo_owner"
    commit = await _ask(world, lease)
    world.task_id, world.run_id, world.ask, world.asked_checkpoint = (
        task_id, run_id, commit.ask, commit.checkpoint.checkpoint_id,
    )
    return world


async def _answer(world, *, owner="test_q9_repo_owner", answers=("main",)):
    return await world.runs.answer_user_question(
        ask_id=world.ask.ask_id,
        owner_id=owner,
        answers=list(answers),
        channel_type="telegram",
        now=NOW + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_an_answer_resumes_the_same_run_from_its_latest_checkpoint(world) -> None:
    commit = await _answer(world)

    answered, status = commit.events
    assert (answered.type, status.type) == ("question.answered", "task.status.changed")
    assert answered.payload == {"ask_id": world.ask.ask_id, "channel_type": "telegram"}
    assert status.payload == {"status": "running", "resumed_by": "answer"}
    assert answered.run_id == status.run_id == world.run_id
    assert commit.checkpoint_id == world.asked_checkpoint
    assert answered.checkpoint_id == status.checkpoint_id == world.asked_checkpoint
    assert commit.ask.answers == ("main",)
    assert await world.task_status(world.task_id) == "running"
    assert await world.run_status(world.run_id) == CodingRunStatus.RUNNING.value
    assert world.task_id in {item[0] for item in await world.runs.claimable_delivery_tokens(limit=500)}


@pytest.mark.asyncio
async def test_an_answer_lands_once(world) -> None:
    assert await _answer(world) is not None
    assert await _answer(world, answers=("other",)) is None
    assert (await world.asks.for_call(world.task_id, world.run_id, "a1")).answers == ("main",)


@pytest.mark.asyncio
async def test_only_the_owner_answers(world) -> None:
    assert await _answer(world, owner=OTHER) is None
    assert (await world.asks.for_call(world.task_id, world.run_id, "a1")).status == "waiting"
    assert await world.task_status(world.task_id) == "waiting_user"


@pytest.mark.asyncio
async def test_a_task_no_longer_waiting_keeps_its_ask_waiting(world) -> None:
    """The transaction rolls back -- the ask is not consumed by a task that moved on."""
    if isinstance(world, PostgresWorld):
        from neos.database.connection import db_manager

        async with await db_manager.get_session() as session:
            await session.execute(
                text("UPDATE coding_tasks SET status = 'cancelling' WHERE task_id = :t"),
                {"t": world.task_id},
            )
            await session.commit()
    else:
        world.runs.task_statuses[world.task_id] = "cancelling"

    assert await _answer(world) is None
    assert (await world.asks.for_call(world.task_id, world.run_id, "a1")).status == "waiting"


# ---- CodingRunService.resume_answered (the Q10b wake) ----------------------------


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_resume_answered_wakes_the_worker_once_with_the_latest_checkpoint() -> None:
    from tests.coding.application.test_run_service import make_run_service

    world = MemoryWorld()
    task_id, run_id, lease = await world.waiting_task()
    commit = await _ask(world, lease)
    service = await make_run_service(world.runs)
    woken = []

    async def wake(task, checkpoint_id):
        woken.append((task, checkpoint_id))

    service.set_wake(wake)

    resumed = await service.resume_answered(
        ask_id=commit.ask.ask_id, owner_id="u1", answers=["main"], channel_type="slack"
    )
    again = await service.resume_answered(
        ask_id=commit.ask.ask_id, owner_id="u1", answers=["main"], channel_type="slack"
    )

    assert resumed is not None and again is None
    assert woken == [(task_id, commit.checkpoint.checkpoint_id)]
