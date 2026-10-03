"""Q5b: a monitor pause is the Q10b pause -- one contract in memory and in Postgres.

`pause_task` takes the judgement kind; the monitor's is `monitor.judged`. And the
monitor's cursor (MP6) reads the real ledger: seq order is commit order per task,
so a cursor never skips an event -- including the pause's own judgement, which
is what keeps the cadence after a resume.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.domain.durability import StaleExecutionLease
from neos.coding.domain.phases import CodingCheckpoint, CodingRunStatus
from neos.coding.monitor.monitor import TrajectoryMonitor
from neos.coding.monitor.rules import FallbackThresholds
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.database.connection import db_manager
from tests.coding.fakes import InMemoryCodingRunRepository

OWNER = "test_q5b_monitor_owner"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
JUDGED = {
    "tool_results": 2,
    "mode": "interactive",
    "enforced": True,
    "judge": "jev",
    "probability": 0.93,
    "pause_at_or_above": 0.8,
    "would_pause": True,
    "rubric_digest": "abc",
    "model": "jev-1.13.0",
}


async def _seed_owner() -> None:
    async with await db_manager.get_session() as session:
        await session.execute(
            text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
            {"u": OWNER, "e": f"{OWNER}@example.com"},
        )
        await session.commit()


class PostgresWorld:
    def __init__(self) -> None:
        self.runs = PostgresCodingRunRepository(db_manager.get_session)
        self.events = PostgresCodingService(db_manager.get_session)

    async def running_task(self):
        task = await self.events.create_task(owner_id=OWNER, prompt="p")
        run = await self.runs.ensure_run_started(
            task_id=task.task_id, instruction="p", development_mode=True, now=NOW
        )
        await self.runs.save_checkpoint(
            CodingCheckpoint(
                checkpoint_id=f"cc_{uuid4().hex}",
                task_id=task.task_id,
                run_id=run.run_id,
                seq=1,
                loop_state={},
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


class MemoryWorld:
    def __init__(self) -> None:
        self.runs = InMemoryCodingRunRepository(task_prompts={"ct_1": "p"})

    async def running_task(self):
        run = await self.runs.ensure_run_started(
            task_id="ct_1", instruction="p", development_mode=True, now=NOW
        )
        self.runs.task_owners["ct_1"] = OWNER
        self.runs.checkpoints.append(CodingCheckpoint("cc_1", "ct_1", run.run_id, 1, {}, "rev", NOW))
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


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_owner()
    return PostgresWorld()


async def _pause(world, lease):
    """The judgement saw two tool results -- what the cadence test leaves in the ledger."""
    return await world.runs.pause_task(
        lease=lease,
        judgement_type="monitor.judged",
        judgement=JUDGED,
        reason_code="monitor_jev",
        now=NOW,
    )


@pytest.mark.asyncio
async def test_a_monitor_pause_is_one_transaction_and_leaves_the_run(world) -> None:
    task_id, run_id, lease = await world.running_task()

    commit = await _pause(world, lease)

    judged, status = commit.events
    assert (judged.type, status.type) == ("monitor.judged", "task.status.changed")
    assert judged.payload == JUDGED
    assert status.payload == {"status": "paused", "reason_code": "monitor_jev"}
    assert judged.seq + 1 == status.seq
    assert await world.task_status(task_id) == "paused"
    assert await world.run_status(run_id) == CodingRunStatus.RUNNING.value


@pytest.mark.asyncio
async def test_a_paused_task_is_not_paused_again(world) -> None:
    """If the envelope paused first, a monitor pause on the same lease is stale."""
    _task_id, _run_id, lease = await world.running_task()
    await world.runs.pause_task(
        lease=lease,
        judgement_type="budget.judged",
        judgement={"would_pause": True, "enforced": True},
        reason_code="budget_envelope_exhausted",
        now=NOW,
    )

    with pytest.raises(StaleExecutionLease):
        await _pause(world, lease)


@pytest.mark.asyncio
async def test_the_cursor_reads_the_real_ledger_and_keeps_the_cadence_after_a_pause() -> None:
    await _seed_owner()
    world = PostgresWorld()
    task_id, run_id, lease = await world.running_task()
    monitor = TrajectoryMonitor(
        scorer=object(),
        pause_at_or_above=0.8,
        limits=FallbackThresholds(1, 2, 10, 3, 3, 1, 4.0, 5),
        every_n_tool_results=2,
        enforce=True,
    )
    reads = []

    async def reader(task, *, after_seq=0, limit=500):
        reads.append(after_seq)
        return await world.events.list_after(task, after_seq=after_seq, limit=limit)

    for name in ("a", "b"):
        await world.events.append(
            task_id=task_id, event_type="tool.completed", payload={"name": name}, run_id=run_id
        )
    first = await monitor.read_ledger(reader, task_id)
    assert monitor.due(first)

    commit = await _pause(world, lease)
    reads.clear()
    after = await monitor.read_ledger(reader, task_id)

    assert reads[0] == first[-1].seq  # the cursor, not seq 0
    assert [e.seq for e in after[-2:]] == [e.seq for e in commit.events]
    assert not monitor.due(after)  # the pause's judgement remembers tool_results
    assert [e.seq for e in after] == sorted({e.seq for e in after})
