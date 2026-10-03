"""Q10b: `pause_task` / `resume_paused_task` keep one contract in memory and in Postgres.

A pause is one transaction (judgement, `running -> paused`, status event); the
run stays `running`; workers do not pick a paused task up; only its owner
resumes it, once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.domain.durability import StaleExecutionLease
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.phases import CodingCheckpoint, CodingRunStatus
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.database.connection import db_manager
from tests.coding.fakes import InMemoryCodingRunRepository

OWNER = "test_q10b_pause_owner"
INTRUDER = "test_q10b_pause_intruder"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
JUDGED = {"would_pause": True, "enforced": True, "reason": "budget_envelope_exhausted"}


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (OWNER, INTRUDER):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


class PostgresWorld:
    def __init__(self) -> None:
        self.runs = PostgresCodingRunRepository(db_manager.get_session)

    async def running_task(self):
        task = await PostgresCodingService(db_manager.get_session).create_task(
            owner_id=OWNER, prompt="p"
        )
        run = await self.runs.ensure_run_started(
            task_id=task.task_id, instruction="p", development_mode=True, now=NOW
        )
        await self.runs.save_checkpoint(
            CodingCheckpoint(
                checkpoint_id=f"cc_{uuid4().hex}",
                task_id=task.task_id,
                run_id=run.run_id,
                seq=1,
                loop_state={"cost_micros": 1},
                workspace_revision="rev",
                created_at=NOW,
            )
        )
        lease = await self.runs.acquire_execution_lease(
            task_id=task.task_id,
            run_id=run.run_id,
            worker_id="w1",
            now=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
        return task.task_id, run.run_id, lease

    async def task_status(self, task_id):
        async with await db_manager.get_session() as session:
            return (
                await session.execute(
                    text("SELECT status FROM coding_tasks WHERE task_id = :t"), {"t": task_id}
                )
            ).scalar_one()

    async def run_status(self, run_id):
        async with await db_manager.get_session() as session:
            return (
                await session.execute(
                    text("SELECT status FROM coding_runs WHERE run_id = :r"), {"r": run_id}
                )
            ).scalar_one()

    async def claimable(self, task_id):
        ids = await self.runs.claimable_task_ids(limit=500)
        tokens = await self.runs.claimable_delivery_tokens(limit=500)
        return task_id in ids, task_id in {item[0] for item in tokens}


class MemoryWorld:
    def __init__(self) -> None:
        self.runs = InMemoryCodingRunRepository(task_prompts={"ct_1": "p"})

    async def running_task(self):
        run = await self.runs.ensure_run_started(
            task_id="ct_1", instruction="p", development_mode=True, now=NOW
        )
        self.runs.task_owners["ct_1"] = OWNER
        self.runs.checkpoints.append(
            CodingCheckpoint("cc_1", "ct_1", run.run_id, 1, {"cost_micros": 1}, "rev", NOW)
        )
        lease = await self.runs.acquire_execution_lease(
            task_id="ct_1",
            run_id=run.run_id,
            worker_id="w1",
            now=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
        return "ct_1", run.run_id, lease

    async def task_status(self, task_id):
        return self.runs.task_statuses[task_id]

    async def run_status(self, run_id):
        return self.runs.active_run.status.value

    async def claimable(self, task_id):
        ids = await self.runs.claimable_task_ids(limit=500)
        tokens = await self.runs.claimable_delivery_tokens(limit=500)
        return task_id in ids, task_id in {item[0] for item in tokens}


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


async def _pause(world, lease):
    return await world.runs.pause_task(
        lease=lease,
        judgement_type="budget.judged",
        judgement=JUDGED,
        reason_code="budget_envelope_exhausted",
        now=NOW,
    )


@pytest.mark.asyncio
async def test_a_pause_writes_the_judgement_then_the_status_and_leaves_the_run(world) -> None:
    task_id, run_id, lease = await world.running_task()

    commit = await _pause(world, lease)

    judged, status = commit.events
    assert (judged.type, status.type) == ("budget.judged", "task.status.changed")
    assert judged.payload == JUDGED
    assert status.payload == {"status": "paused", "reason_code": "budget_envelope_exhausted"}
    assert judged.seq + 1 == status.seq
    assert judged.checkpoint_id is not None and judged.checkpoint_id == status.checkpoint_id
    assert judged.run_id == status.run_id == run_id
    assert await world.task_status(task_id) == "paused"
    assert await world.run_status(run_id) == CodingRunStatus.RUNNING.value


@pytest.mark.asyncio
async def test_no_worker_picks_up_a_paused_task(world) -> None:
    task_id, _run_id, lease = await world.running_task()
    assert await world.claimable(task_id) == (True, True)

    await _pause(world, lease)

    assert await world.claimable(task_id) == (False, False)


@pytest.mark.asyncio
async def test_a_paused_task_cannot_be_paused_again(world) -> None:
    _task_id, _run_id, lease = await world.running_task()
    await _pause(world, lease)

    with pytest.raises(StaleExecutionLease):
        await _pause(world, lease)


@pytest.mark.asyncio
async def test_only_the_owner_resumes_and_only_once(world) -> None:
    task_id, run_id, lease = await world.running_task()
    await _pause(world, lease)

    with pytest.raises(CodingTaskNotFound):
        await world.runs.resume_paused_task(task_id=task_id, owner_id=INTRUDER, now=NOW)
    assert await world.task_status(task_id) == "paused"

    commit = await world.runs.resume_paused_task(task_id=task_id, owner_id=OWNER, now=NOW)

    assert commit is not None
    assert commit.event.payload == {"status": "running", "resumed_by": "owner"}
    assert commit.event.run_id == run_id
    assert commit.checkpoint_id is not None
    assert await world.task_status(task_id) == "running"
    assert await world.claimable(task_id) == (True, True)
    assert await world.runs.resume_paused_task(task_id=task_id, owner_id=OWNER, now=NOW) is None


@pytest.mark.asyncio
async def test_a_running_task_is_not_resumed(world) -> None:
    task_id, _run_id, _lease = await world.running_task()

    assert await world.runs.resume_paused_task(task_id=task_id, owner_id=OWNER, now=NOW) is None
    assert await world.task_status(task_id) == "running"


@pytest.mark.asyncio
async def test_an_unknown_task_is_not_found(world) -> None:
    with pytest.raises(CodingTaskNotFound):
        await world.runs.resume_paused_task(task_id="ct_nope", owner_id=OWNER, now=NOW)


@pytest.mark.asyncio
async def test_a_lease_that_was_let_go_cannot_pause(world) -> None:
    task_id, _run_id, lease = await world.running_task()
    await world.runs.release_execution_lease(lease, now=NOW)

    with pytest.raises(StaleExecutionLease):
        await _pause(world, lease)
    assert await world.task_status(task_id) == "running"
