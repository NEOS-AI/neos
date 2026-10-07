"""Q9a: `request_user_answer` keeps one contract in memory and in Postgres.

The ask is one transaction (pending ask, checkpoint, `question.asked`,
`running -> waiting_user`, status event); the run stays `running`; workers do
not pick a waiting task up; a second question of the same agent writes nothing;
cancelling the task closes its question (design §5 · §8.1). Users are `test_q9_*`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.domain.durability import StaleExecutionLease
from neos.coding.domain.models import CodingTaskMode
from neos.coding.domain.phases import CodingCheckpoint, CodingRunStatus
from neos.coding.model.base import ToolCallCompleted
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.tools.registry import CodingToolRegistry
from neos.database.connection import db_manager
from neos.standing.asks import PostgresPendingAskStore
from neos.standing.store import PostgresStandingAgentStore
from tests.coding.fakes import InMemoryCodingRunRepository

OWNER = "test_q9_repo_owner"
OTHER = "test_q9_repo_other"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
ASK = {"questions": ["Which branch?"]}
CALL = ToolCallCompleted("a1", "ask_user.v1", ASK)
VALIDATED = CodingToolRegistry.default(command_allowlist=frozenset({"git"})).validate(
    "ask_user.v1", ASK
)
STATE = {"pending_tool_calls": [{"tool_call_id": "a1"}], "pending_tool_index": 0}


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (OWNER, OTHER):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


class PostgresWorld:
    def __init__(self) -> None:
        self.runs = PostgresCodingRunRepository(db_manager.get_session)
        self.asks = PostgresPendingAskStore(db_manager.get_session)
        self.agents = PostgresStandingAgentStore(db_manager.get_session)
        self.coding = PostgresCodingService(db_manager.get_session)
        self.agent_id = None

    async def agent(self) -> str:
        if self.agent_id is None:
            self.agent_id = (await self.agents.create(OWNER, "Dot")).agent_id
        return self.agent_id

    async def waiting_task(self):
        agent_id = await self.agent()
        task = await self.coding.create_task(
            owner_id=OWNER, prompt="p", mode=CodingTaskMode.AUTONOMOUS, agent_id=agent_id
        )
        run = await self.runs.ensure_run_started(
            task_id=task.task_id, instruction="p", development_mode=True, now=NOW
        )
        await self.runs.save_checkpoint(
            CodingCheckpoint(f"cc_{uuid4().hex}", task.task_id, run.run_id, 1, {"x": 1}, "rev", NOW)
        )
        lease = await self.runs.acquire_execution_lease(
            task_id=task.task_id,
            run_id=run.run_id,
            worker_id=f"w_{uuid4().hex[:6]}",
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

    async def event_count(self, task_id):
        async with await db_manager.get_session() as session:
            return (
                await session.execute(
                    text("SELECT COUNT(*) FROM coding_events WHERE task_id = :t"), {"t": task_id}
                )
            ).scalar_one()


class MemoryWorld:
    def __init__(self) -> None:
        self.runs = InMemoryCodingRunRepository(task_prompts={})
        self.asks = self.runs.asks
        self._n = 0

    async def agent(self) -> str:
        return "sa_mem"

    async def waiting_task(self):
        self._n += 1
        task_id = f"ct_{self._n}"
        self.runs.task_prompts[task_id] = "p"
        self.runs.task_statuses[task_id] = "queued"
        self.runs.task_agents[task_id] = "sa_mem"
        run = await self.runs.ensure_run_started(
            task_id=task_id, instruction="p", development_mode=True, now=NOW
        )
        self.runs.checkpoints.append(CodingCheckpoint(f"cc_{task_id}", task_id, run.run_id, 1, {"x": 1}, "rev", NOW))
        lease = await self.runs.acquire_execution_lease(
            task_id=task_id,
            run_id=run.run_id,
            worker_id="w1",
            now=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
        return task_id, run.run_id, lease

    async def task_status(self, task_id):
        return self.runs.task_statuses[task_id]

    async def run_status(self, run_id):
        return next(run for run in self.runs.created_runs if run.run_id == run_id).status.value

    async def event_count(self, task_id):
        return None  # the fake keeps no ledger; the Postgres half checks it


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


async def _ask(world, lease, *, agent_id=None):
    return await world.runs.request_user_answer(
        lease=lease,
        tool_call=CALL,
        validated=VALIDATED,
        loop_state=STATE,
        workspace_revision="rev",
        agent_id=agent_id or await world.agent(),
        reply_session_id="v2:slack:T1:D1:-",
        reply_channel_type="slack",
        asked_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )


@pytest.mark.asyncio
async def test_an_ask_is_one_transaction_and_the_run_stays_running(world) -> None:
    task_id, run_id, lease = await world.waiting_task()

    commit = await _ask(world, lease)

    asked, status = commit.events
    assert (asked.type, status.type) == ("question.asked", "task.status.changed")
    assert status.payload == {"status": "waiting_user"}
    assert asked.payload["ask_id"] == commit.ask.ask_id
    assert asked.payload["questions"] == ["Which branch?"]
    assert asked.seq + 1 == status.seq
    assert asked.checkpoint_id == status.checkpoint_id == commit.checkpoint.checkpoint_id
    assert commit.checkpoint.loop_state == STATE
    assert asked.tool_call_id == "a1" and asked.run_id == run_id
    assert await world.task_status(task_id) == "waiting_user"
    assert await world.run_status(run_id) == CodingRunStatus.RUNNING.value
    assert await world.asks.for_call(task_id, run_id, "a1") == commit.ask


@pytest.mark.asyncio
async def test_no_worker_picks_up_a_waiting_task(world) -> None:
    task_id, _run_id, lease = await world.waiting_task()
    assert task_id in {item[0] for item in await world.runs.claimable_delivery_tokens(limit=500)}

    await _ask(world, lease)

    assert task_id not in {item[0] for item in await world.runs.claimable_delivery_tokens(limit=500)}


@pytest.mark.asyncio
async def test_a_second_question_of_the_agent_writes_nothing(world) -> None:
    """Review Focus 3 in the transaction: `None`, and the second task is untouched."""
    _first, _run, first_lease = await world.waiting_task()
    second_task, second_run, second_lease = await world.waiting_task()
    await _ask(world, first_lease)
    events_before = await world.event_count(second_task)

    assert await _ask(world, second_lease) is None

    assert await world.task_status(second_task) == "running"
    assert await world.asks.for_call(second_task, second_run, "a1") is None
    assert await world.event_count(second_task) == events_before


@pytest.mark.asyncio
async def test_a_task_of_another_agent_is_stale(world) -> None:
    _task_id, _run_id, lease = await world.waiting_task()

    with pytest.raises(StaleExecutionLease):
        await _ask(world, lease, agent_id="sa_someone_else")


@pytest.mark.asyncio
async def test_a_waiting_task_cannot_ask_again(world) -> None:
    _task_id, _run_id, lease = await world.waiting_task()
    await _ask(world, lease)

    with pytest.raises(StaleExecutionLease):
        await _ask(world, lease)


@pytest.mark.asyncio
async def test_cancelling_the_task_closes_its_question(world) -> None:
    """Design §8.1. Mutation: drop the close -> the agent is `ask_pending` until expiry."""
    task_id, run_id, lease = await world.waiting_task()
    await _ask(world, lease)

    await world.runs.mark_task_cancelled(task_id=task_id, now=NOW)

    assert (await world.asks.for_call(task_id, run_id, "a1")).status == "cancelled"
    assert await world.asks.waiting_for_agent(await world.agent()) is None
    assert await world.task_status(task_id) == "cancelled"


# ---- final review fixes (Postgres only: they are about the real schema) -------------


@pytest.mark.asyncio
async def test_a_deleted_agent_cannot_ask() -> None:
    """Final review (Q9-2): the lock query requires a live agent. Mutation: drop the
    `agent.deleted_at IS NULL` -> the ask is written for a deleted agent."""
    await _seed_users()
    world = PostgresWorld()
    task_id, run_id, lease = await world.waiting_task()
    assert await world.agents.delete(OWNER, await world.agent())

    with pytest.raises(StaleExecutionLease):
        await _ask(world, lease)

    assert await world.task_status(task_id) == "running"
    assert await world.asks.for_call(task_id, run_id, "a1") is None


@pytest.mark.asyncio
async def test_cancel_without_the_pending_asks_table_still_cancels(monkeypatch, caplog) -> None:
    """Final review Important 2: a database without migration 095 must still cancel.
    The seam points the close at a relation that does not exist -- a real Postgres
    `undefined_table` -- without altering the shared test DB."""
    from neos.standing import asks as asks_module

    await _seed_users()
    world = PostgresWorld()
    task_id, _run_id, _lease = await world.waiting_task()
    monkeypatch.setattr(asks_module, "PENDING_ASKS_TABLE", "standing_pending_asks_absent_q9")
    monkeypatch.setattr(asks_module, "_warned_missing_pending_asks", False)
    caplog.set_level("WARNING", logger="neos.standing.asks")

    await world.runs.mark_task_cancelled(task_id=task_id, now=NOW)
    await world.runs.mark_task_cancelled(task_id=task_id, now=NOW)

    assert await world.task_status(task_id) == "cancelled"
    warnings = [r for r in caplog.records if "standing_pending_asks" in r.getMessage()]
    assert len(warnings) == 1  # once


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1 / 0",  # any other database error
        "UPDATE standing_pending_asks_unrelated_q9 SET status = 'x'",  # another missing table
    ],
)
@pytest.mark.asyncio
async def test_any_other_close_error_still_fails_the_cancel(monkeypatch, statement) -> None:
    """Only an undefined `standing_pending_asks` is "nothing to close"."""
    from sqlalchemy.exc import DBAPIError

    from neos.standing import asks as asks_module

    async def broken_close(session, task_id):
        await session.execute(text(statement))

    await _seed_users()
    world = PostgresWorld()
    task_id, _run_id, _lease = await world.waiting_task()
    monkeypatch.setattr(asks_module, "cancel_for_task_in_session", broken_close)

    with pytest.raises(DBAPIError):
        await world.runs.mark_task_cancelled(task_id=task_id, now=NOW)

    assert await world.task_status(task_id) == "running"  # the cancel rolled back
