"""Q13d: the standing agent activity feed (design §7.1).

The feed merges the ledgers of every task the agent opened. The test the design
asked for is "every event exactly once" -- per-task `seq` cannot be the merged
cursor, and `created_at` cannot either: it is the caller's clock, and a late
commit would land behind a cursor that already passed it. One contract over the
in-memory and Postgres sources; the late-commit case is Postgres only because
only there do two transactions exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.persistence.postgres import PostgresCodingService
from neos.database.connection import db_manager
from neos.standing.activity import (
    START,
    FeedCursor,
    InMemoryActivitySource,
    PostgresActivitySource,
    agent_activity,
)
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore
from neos.standing.tasks import open_agent_task

ALICE = "test_agent_activity_alice"
BOB = "test_agent_activity_bob"


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text(
                    "INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"
                ),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


class World:
    def __init__(self, agents, coding, source, hide) -> None:
        self.agents = agents
        self.coding = coding
        self.source = source
        self.hide = hide  # soft-delete a task the way archive does

    async def feed(self, agent_id=None, *, after=None, limit=100, owner=ALICE):
        return await agent_activity(
            self.agents, self.source,
            owner_id=owner, agent_id=agent_id, after=after, limit=limit,
        )

    async def drain(self, *, after=None, limit=100):
        """Page to the end; every (task_id, seq) in the order it arrived."""
        seen, cursor = [], after
        while True:
            page = await self.feed(after=cursor, limit=limit)
            if not page.events:
                return seen, page.next
            seen += [(event.task_id, event.seq) for event in page.events]
            cursor = page.next

    async def say(self, task_id: str, n: int = 1, *, now=None) -> None:
        for _ in range(n):
            await self.coding.events.append(
                task_id=task_id, event_type="model.delta", payload={}, now=now
            )


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        repo = InMemoryCodingTaskRepository()
        events = InMemoryCodingEventStore()
        return World(
            InMemoryStandingAgentStore(),
            CodingTaskService(repo, events),
            InMemoryActivitySource(repo, events),
            lambda task_id: _async(repo.mark_deleted, task_id),
        )
    await _seed_users()

    async def hide(task_id: str) -> None:
        async with await db_manager.get_session() as session:
            await session.execute(
                text("UPDATE coding_tasks SET deleted_at = NOW() WHERE task_id = :t"),
                {"t": task_id},
            )
            await session.commit()

    return World(
        PostgresStandingAgentStore(db_manager.get_session),
        PostgresCodingService(db_manager.get_session),
        PostgresActivitySource(db_manager.get_session),
        hide,
    )


async def _async(fn, *args):
    fn(*args)


async def _open(world: World, owner: str = ALICE) -> str:
    task = await open_agent_task(world.agents, world.coding, owner_id=owner, prompt="p")
    return task.task_id


@pytest.mark.asyncio
async def test_an_agent_with_no_tasks_has_an_empty_feed_and_keeps_its_cursor(world) -> None:
    await world.agents.create(ALICE, "Dot")

    page = await world.feed()

    assert page.events == []
    assert page.next == START.encode()


@pytest.mark.asyncio
async def test_every_event_of_every_agent_task_exactly_once_in_task_order(world) -> None:
    await world.agents.create(ALICE, "Dot")
    first = await _open(world)
    second = await _open(world)
    await world.say(first, 2)
    await world.say(second, 3)
    await world.say(first, 1)

    for limit in (1, 2, 100):
        seen, _ = await world.drain(limit=limit)
        assert sorted(seen) == sorted(
            [(first, s) for s in (1, 2, 3, 4)] + [(second, s) for s in (1, 2, 3, 4)]
        ), f"limit={limit}"
        for task_id in (first, second):
            mine = [seq for t, seq in seen if t == task_id]
            assert mine == sorted(mine), f"limit={limit}"


@pytest.mark.asyncio
async def test_only_this_agents_tasks_are_in_the_feed(world) -> None:
    """A person's own task and someone else's agent task stay out."""
    await world.agents.create(ALICE, "Dot")
    await world.agents.create(BOB, "Bobby")
    mine = await _open(world)
    human = await world.coding.create_task(owner_id=ALICE, prompt="by hand")
    bobs = await _open(world, owner=BOB)
    await world.say(human.task_id)
    await world.say(bobs)

    seen, _ = await world.drain()

    assert {task_id for task_id, _ in seen} == {mine}


@pytest.mark.asyncio
async def test_an_event_stamped_before_the_cursor_is_still_delivered(world) -> None:
    """The caller's clock is not the cursor. Mutation: page by created_at -> this
    event lands behind the cursor and is never seen."""
    await world.agents.create(ALICE, "Dot")
    task_id = await _open(world)
    _, cursor = await world.drain()

    await world.say(task_id, now=datetime.now(UTC) - timedelta(hours=1))
    seen, _ = await world.drain(after=cursor)

    assert seen == [(task_id, 2)]


@pytest.mark.asyncio
async def test_an_archived_task_leaves_the_feed_like_it_leaves_the_task_list(world) -> None:
    await world.agents.create(ALICE, "Dot")
    kept = await _open(world)
    gone = await _open(world)

    await world.hide(gone)
    seen, _ = await world.drain()

    assert {task_id for task_id, _ in seen} == {kept}


@pytest.mark.asyncio
async def test_someone_elses_agent_has_no_feed(world) -> None:
    """Alice has an agent too -- so a feed that ignored the id would answer with
    hers instead of None."""
    await world.agents.create(ALICE, "Dot")
    bobs = await world.agents.create(BOB, "Bobby")
    await _open(world, owner=BOB)

    assert await world.feed(bobs.agent_id) is None
    assert await world.feed("sa_missing") is None
    assert (await world.feed(bobs.agent_id, owner=BOB)).events != []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-cursor", "W10", FeedCursor(-1, "", 0).encode()])
async def test_an_unreadable_cursor_is_a_value_error(world, bad) -> None:
    await world.agents.create(ALICE, "Dot")

    with pytest.raises(ValueError):
        await world.feed(after=bad)


@pytest.mark.asyncio
async def test_a_limit_below_one_still_reads_one(world) -> None:
    await world.agents.create(ALICE, "Dot")
    await _open(world)

    assert len((await world.feed(limit=0)).events) == 1


@pytest.mark.asyncio
async def test_the_in_memory_log_keeps_events_appended_whole() -> None:
    """`append_event` is the second way into the in-memory store."""
    from neos.coding.domain.events import make_event

    events = InMemoryCodingEventStore()
    event = make_event(
        task_id="ct_1", seq=1, event_type="task.created", payload={},
        now=datetime.now(UTC),
    )
    await events.append_event(event)

    assert events.in_append_order() == [event]


# -- Postgres only --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_late_commit_is_not_skipped() -> None:
    """Transaction A writes to the first task and stays open; B writes to the
    second and commits. A reader must not move its cursor past A -- otherwise,
    when A commits, its event sits behind the cursor for ever. Mutation: drop
    the `pg_snapshot_xmin` guard."""
    await _seed_users()
    agents = PostgresStandingAgentStore(db_manager.get_session)
    coding = PostgresCodingService(db_manager.get_session)
    world = World(agents, coding, PostgresActivitySource(db_manager.get_session), None)
    await agents.create(ALICE, "Dot")
    first = await _open(world)
    second = await _open(world)
    _, cursor = await world.drain()

    async with await db_manager.get_session() as late:
        async with late.begin():
            await coding.append_in_session(
                late, task_id=first, event_type="model.delta", payload={},
                now=datetime.now(UTC),
            )
            await world.say(second)
            during, cursor = await world.drain(after=cursor)
        # A commits here.
    after, _ = await world.drain(after=cursor)

    assert during == []  # held back, not skipped
    assert sorted(during + after) == sorted([(first, 2), (second, 2)])
