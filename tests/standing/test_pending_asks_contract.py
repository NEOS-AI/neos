"""Q9a: one contract, two stores, for an agent's pending question (migration 095).

The in-memory store and the Postgres store must answer the same way
(docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §4). The Postgres half runs on the real
`_test` database. Users are `test_q9_*` -- another track shares the test DB.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from neos.coding.domain.models import CodingTaskMode
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.database.connection import db_manager
from neos.standing.asks import InMemoryPendingAskStore, PendingAsk, PostgresPendingAskStore
from neos.standing.store import PostgresStandingAgentStore

OWNER = "test_q9_asks_owner"
OTHER = "test_q9_asks_other"
THIRD = "test_q9_asks_third"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=24)
QUESTIONS = ["Which branch?", {"prompt": "Run tests?", "options": [{"label": "yes"}, {"label": "no"}]}]
MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "095_add_standing_pending_asks.sql"


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (OWNER, OTHER, THIRD):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


class MemoryWorld:
    def __init__(self) -> None:
        self.store = InMemoryPendingAskStore()
        self._n = 0

    async def agent(self, owner: str = OWNER) -> str:
        self._n += 1
        return f"sa_mem_{self._n}"

    async def task(self, agent_id: str) -> tuple[str, str]:
        self._n += 1
        return f"ct_mem_{self._n}", f"cr_mem_{self._n}"


class PostgresWorld:
    def __init__(self) -> None:
        self.store = PostgresPendingAskStore(db_manager.get_session)
        self.agents = PostgresStandingAgentStore(db_manager.get_session)
        self.coding = PostgresCodingService(db_manager.get_session)
        self.runs = PostgresCodingRunRepository(db_manager.get_session)
        self._owners: dict[str, str] = {}

    async def agent(self, owner: str = OWNER) -> str:
        agent = await self.agents.create(owner, f"Dot-{owner}-{len(self._owners)}")
        self._owners[agent.agent_id] = owner
        return agent.agent_id

    async def task(self, agent_id: str) -> tuple[str, str]:
        task = await self.coding.create_task(
            owner_id=self._owners[agent_id],
            prompt="p",
            mode=CodingTaskMode.AUTONOMOUS,
            agent_id=agent_id,
        )
        run = await self.runs.ensure_run_started(
            task_id=task.task_id, instruction="p", development_mode=True, now=NOW
        )
        return task.task_id, run.run_id


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


async def _open(world, agent_id, task_id, run_id, call="toolu_1", **overrides):
    kwargs = dict(
        agent_id=agent_id,
        task_id=task_id,
        run_id=run_id,
        tool_call_id=call,
        questions=QUESTIONS,
        reply_session_id="v2:slack:T1:D1:-",
        asked_at=NOW,
        expires_at=LATER,
    )
    kwargs.update(overrides)
    return await world.store.open(**kwargs)


@pytest.mark.asyncio
async def test_an_open_ask_reads_back_by_agent_and_by_call(world) -> None:
    agent = await world.agent()
    task_id, run_id = await world.task(agent)

    ask = await _open(world, agent, task_id, run_id)

    assert isinstance(ask, PendingAsk) and ask.ask_id.startswith("spa_")
    assert (ask.status, ask.answers, ask.answered_at) == ("waiting", None, None)
    assert ask.questions == (QUESTIONS[0], QUESTIONS[1])
    assert ask.reply_session_id == "v2:slack:T1:D1:-"
    assert await world.store.waiting_for_agent(agent) == ask
    assert await world.store.for_call(task_id, run_id, "toolu_1") == ask
    assert await world.store.for_call(task_id, run_id, "toolu_other") is None


@pytest.mark.asyncio
async def test_one_waiting_ask_per_agent(world) -> None:
    """Review Focus 3: the second task of the same agent does not wait."""
    agent = await world.agent()
    first_task = await world.task(agent)
    second_task = await world.task(agent)

    first = await _open(world, agent, *first_task)
    second = await _open(world, agent, *second_task)

    assert first is not None
    assert second is None
    assert await world.store.for_call(*second_task, "toolu_1") is None
    assert await world.store.waiting_for_agent(agent) == first


@pytest.mark.asyncio
async def test_concurrent_opens_for_one_agent_leave_one_waiting(world) -> None:
    """The "one" lives in the partial unique index: race two tasks, one wins."""
    agent = await world.agent()
    tasks = [await world.task(agent) for _ in range(4)]

    results = await asyncio.gather(*(_open(world, agent, *task) for task in tasks))

    assert len([ask for ask in results if ask is not None]) == 1


@pytest.mark.asyncio
async def test_two_agents_wait_independently(world) -> None:
    mine = await world.agent(OWNER)
    theirs = await world.agent(OTHER)

    assert await _open(world, mine, *await world.task(mine)) is not None
    assert await _open(world, theirs, *await world.task(theirs)) is not None


@pytest.mark.asyncio
async def test_an_answered_ask_frees_the_agent_for_the_next_one(world) -> None:
    agent = await world.agent()
    task_id, run_id = await world.task(agent)
    first = await _open(world, agent, task_id, run_id, "toolu_1")

    await world.store.answer(first.ask_id, ["main", "yes"], now=NOW + timedelta(minutes=1))
    second = await _open(world, agent, task_id, run_id, "toolu_2")

    assert second is not None and second.ask_id != first.ask_id


@pytest.mark.asyncio
async def test_the_same_call_is_one_ask(world) -> None:
    agent = await world.agent()
    task_id, run_id = await world.task(agent)
    first = await _open(world, agent, task_id, run_id)
    await world.store.answer(first.ask_id, ["a", "b"], now=NOW)

    assert await _open(world, agent, task_id, run_id) is None


@pytest.mark.asyncio
async def test_an_answer_lands_once(world) -> None:
    agent = await world.agent()
    task_id, run_id = await world.task(agent)
    ask = await _open(world, agent, task_id, run_id)
    at = NOW + timedelta(minutes=3)

    answered = await world.store.answer(ask.ask_id, ["main", "yes"], now=at)
    again = await world.store.answer(ask.ask_id, ["other", "no"], now=at)

    assert answered.status == "answered"
    assert answered.answers == ("main", "yes")
    assert answered.answered_at == at
    assert again is None
    assert (await world.store.for_call(task_id, run_id, "toolu_1")).answers == ("main", "yes")
    assert await world.store.waiting_for_agent(agent) is None


@pytest.mark.asyncio
async def test_expire_due_takes_only_waiting_asks_past_their_time(world) -> None:
    agent_a = await world.agent(OWNER)
    agent_b = await world.agent(OTHER)
    agent_c = await world.agent(THIRD)
    due = await _open(world, agent_a, *await world.task(agent_a), expires_at=NOW + timedelta(hours=1))
    fresh = await _open(world, agent_b, *await world.task(agent_b), expires_at=NOW + timedelta(hours=5))
    answered = await _open(world, agent_c, *await world.task(agent_c), expires_at=NOW + timedelta(hours=1))
    await world.store.answer(answered.ask_id, ["x", "y"], now=NOW)

    expired = await world.store.expire_due(NOW + timedelta(hours=2))

    assert [ask.ask_id for ask in expired] == [due.ask_id]
    assert expired[0].status == "expired"
    assert (await world.store.for_call(due.task_id, due.run_id, "toolu_1")).status == "expired"
    assert (await world.store.waiting_for_agent(agent_b)) == fresh
    assert await world.store.expire_due(NOW + timedelta(hours=2)) == []


@pytest.mark.asyncio
async def test_cancel_for_task_closes_its_waiting_ask(world) -> None:
    agent = await world.agent()
    task_id, run_id = await world.task(agent)
    await _open(world, agent, task_id, run_id)

    assert await world.store.cancel_for_task(task_id) == 1
    assert (await world.store.for_call(task_id, run_id, "toolu_1")).status == "cancelled"
    assert await world.store.waiting_for_agent(agent) is None
    assert await world.store.cancel_for_task(task_id) == 0


@pytest.mark.asyncio
async def test_expiry_must_follow_the_ask(world) -> None:
    agent = await world.agent()
    task_id, run_id = await world.task(agent)

    with pytest.raises(ValueError):
        await _open(world, agent, task_id, run_id, expires_at=NOW)


# ---- Postgres only -------------------------------------------------------------


async def _count(sql: str, **params) -> int:
    async with await db_manager.get_session() as session:
        return int((await session.execute(text(sql), params)).scalar_one())


@pytest.mark.asyncio
async def test_deleting_the_user_removes_its_asks_in_one_statement() -> None:
    await _seed_users()
    world = PostgresWorld()
    agent = await world.agent()
    await _open(world, agent, *await world.task(agent))
    assert await _count("SELECT COUNT(*) FROM standing_pending_asks WHERE agent_id = :a", a=agent) == 1

    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": OWNER})
        await session.commit()

    assert await _count("SELECT COUNT(*) FROM standing_pending_asks WHERE agent_id = :a", a=agent) == 0


async def _apply_migration() -> None:
    async with db_manager.engine.begin() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(MIGRATION.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_the_migration_applies_twice_and_leaves_one_kind_check() -> None:
    """095 drops 085's unnamed inline CHECK by the name Postgres gave it. If that
    name were wrong the DROP would be silent and the old CHECK would stay beside the
    new one -- so this reads the constraints back and writes a `question_asked` row."""
    await _apply_migration()
    await _apply_migration()

    async with await db_manager.get_session() as session:
        checks = (
            await session.execute(
                text(
                    """
                    SELECT conname, pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = 'standing_notifications'::regclass
                      AND contype = 'c'
                      AND pg_get_constraintdef(oid) LIKE '%kind%'
                    """
                )
            )
        ).all()
    assert [name for name, _ in checks] == ["standing_notifications_kind_check"]
    assert "question_asked" in checks[0][1] and "ask_expired" in checks[0][1]

    await _seed_users()
    world = PostgresWorld()
    agent = await world.agent()
    async with await db_manager.get_session() as session:
        for kind in ("question_asked", "ask_expired"):
            await session.execute(
                text(
                    """
                    INSERT INTO standing_notifications
                        (notification_id, agent_id, kind, dedupe_key, channel_type,
                         channel_id, body)
                    VALUES (:id, :agent, :kind, :key, 'slack', 'D1', 'body')
                    """
                ),
                {"id": f"sn_q9_{kind}", "agent": agent, "kind": kind, "key": f"q9:{kind}"},
            )
        await session.commit()
    assert await _count(
        "SELECT COUNT(*) FROM standing_notifications WHERE agent_id = :a", a=agent
    ) == 2


@pytest.mark.no_db
def test_the_notice_kinds_in_code_match_the_095_check() -> None:
    from neos.standing.notifications import NOTICE_KINDS

    sql = MIGRATION.read_text(encoding="utf-8")
    check = sql[sql.index("ADD CONSTRAINT standing_notifications_kind_check") :]
    assert {kind for kind in NOTICE_KINDS} == {
        token.strip().strip("'")
        for token in check[check.index("(kind IN (") + len("(kind IN (") : check.index("))")].split(",")
    }
