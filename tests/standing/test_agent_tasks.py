"""Q13c: a standing agent opens coding tasks (design §4.2, §5).

One contract, two services -- the in-memory `CodingTaskService` and the
`PostgresCodingService` each had their own `create_task`, so a change that
lands in one only is the failure this file is shaped against.

Real database for the Postgres half: conftest deletes `test%@%` users before
and after; their agents and tasks go with them (both CASCADE on users).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.domain.models import CodingTaskMode
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.database.connection import db_manager
from neos.standing.models import StandingAgentStatus
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore
from neos.standing.tasks import AgentTaskRefused, open_agent_task

ALICE = "test_agent_tasks_alice"
BOB = "test_agent_tasks_bob"


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


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    """(agent store, coding service) -- the same pair of shapes either way."""
    if request.param == "memory":
        return InMemoryStandingAgentStore(), CodingTaskService(
            InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
        )
    await _seed_users()
    return (
        PostgresStandingAgentStore(db_manager.get_session),
        PostgresCodingService(db_manager.get_session),
    )


async def _created_event(coding, task_id: str):
    events = await coding.events.list_after(task_id)
    assert events[0].type == "task.created"
    return events[0]


@pytest.mark.asyncio
async def test_an_agent_task_is_background_owned_by_the_owner_and_signed(world) -> None:
    agents, coding = world
    agent = await agents.create(ALICE, "Dot")

    task = await open_agent_task(agents, coding, owner_id=ALICE, prompt="look around")

    assert task.mode is CodingTaskMode.BACKGROUND
    assert task.owner_id == ALICE
    assert task.agent_id == agent.agent_id
    event = await _created_event(coding, task.task_id)
    assert event.payload["actor"] == f"agent:{agent.agent_id}"
    assert event.payload["mode"] == "background"


@pytest.mark.asyncio
async def test_a_human_task_carries_no_actor(world) -> None:
    """No `actor` means a person (design §5) -- the old shape is unchanged."""
    _agents, coding = world

    task = await coding.create_task(owner_id=ALICE, prompt="fix it")

    assert task.agent_id is None
    assert "actor" not in (await _created_event(coding, task.task_id)).payload


@pytest.mark.asyncio
async def test_work_the_user_handed_over_may_be_autonomous(world) -> None:
    agents, coding = world
    await agents.create(ALICE, "Dot")

    task = await open_agent_task(
        agents, coding, owner_id=ALICE, prompt="p", mode=CodingTaskMode.AUTONOMOUS
    )

    assert task.mode is CodingTaskMode.AUTONOMOUS


@pytest.mark.asyncio
async def test_an_agent_never_opens_an_interactive_task(world) -> None:
    """Interactive says a person is watching -- a false signal from an agent (§9)."""
    agents, coding = world
    await agents.create(ALICE, "Dot")

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(
            agents, coding, owner_id=ALICE, prompt="p", mode=CodingTaskMode.INTERACTIVE
        )

    assert raised.value.reason == "interactive_mode"
    assert await coding.list_owned(ALICE, limit=50) == []


@pytest.mark.asyncio
async def test_someone_elses_agent_is_not_found_and_opens_nothing(world) -> None:
    agents, coding = world
    bobs = await agents.create(BOB, "Bobby")
    await agents.create(ALICE, "Dot")

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(
            agents, coding, owner_id=ALICE, prompt="p", agent_id=bobs.agent_id
        )

    assert raised.value.reason == "agent_not_found"
    assert await coding.list_owned(ALICE, limit=50) == []
    assert await coding.list_owned(BOB, limit=50) == []


@pytest.mark.asyncio
async def test_an_owner_without_an_agent_is_refused(world) -> None:
    agents, coding = world

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(agents, coding, owner_id=ALICE, prompt="p")

    assert raised.value.reason == "agent_not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [StandingAgentStatus.PAUSED, StandingAgentStatus.RETIRED])
async def test_a_stopped_agent_opens_no_new_task(world, status) -> None:
    agents, coding = world
    agent = await agents.create(ALICE, "Dot")
    await agents.update(ALICE, agent.agent_id, status=status)

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(agents, coding, owner_id=ALICE, prompt="p")

    assert raised.value.reason == f"agent_{status.value}"
    assert await coding.list_owned(ALICE, limit=50) == []


@pytest.mark.asyncio
async def test_the_owner_check_is_the_one_that_already_exists(world) -> None:
    """No second ownership path: the owner sees the agent's task through the
    ordinary owner-keyed reads, and nobody else does."""
    agents, coding = world
    await agents.create(ALICE, "Dot")
    task = await open_agent_task(agents, coding, owner_id=ALICE, prompt="p")

    assert (await coding.snapshot(task.task_id, ALICE)).task.agent_id == task.agent_id
    assert [t.task_id for t in await coding.list_owned(ALICE, limit=50)] == [task.task_id]
    assert await coding.snapshot(task.task_id, BOB) is None
    assert await coding.list_owned(BOB, limit=50) == []


# -- Postgres only --------------------------------------------------------


@pytest.mark.asyncio
async def test_every_postgres_reader_returns_the_agent_id() -> None:
    """Five places built `CodingTask` from a row before Q13c; the readers now
    share one column list. Each reader is named here so a new one that forgets
    the column fails by name, not by count."""
    await _seed_users()
    agents = PostgresStandingAgentStore(db_manager.get_session)
    coding = PostgresCodingService(db_manager.get_session)
    repository = CodingTaskRepository(db_manager)
    agent = await agents.create(ALICE, "Dot")
    task = await open_agent_task(agents, coding, owner_id=ALICE, prompt="p")

    read = {
        "service.snapshot": (await coding.snapshot(task.task_id, ALICE)).task,
        "service.list_owned": (await coding.list_owned(ALICE, limit=50))[0],
        "repository.get": await repository.get(task.task_id),
        "repository.get_owned": await repository.get_owned(task.task_id, ALICE),
        "repository.list_owned": (await repository.list_owned(ALICE, limit=50))[0],
    }

    assert {name: t.agent_id for name, t in read.items()} == {
        name: agent.agent_id for name in read
    }


@pytest.mark.asyncio
async def test_deleting_the_owner_takes_the_agent_and_its_tasks_together() -> None:
    """`coding_tasks.agent_id` has no ON DELETE; both rows go by CASCADE from
    users in one statement, so NO ACTION must not block it -- conftest's
    cleanup depends on this."""
    await _seed_users()
    agents = PostgresStandingAgentStore(db_manager.get_session)
    coding = PostgresCodingService(db_manager.get_session)
    await agents.create(ALICE, "Dot")
    task = await open_agent_task(agents, coding, owner_id=ALICE, prompt="p")

    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": ALICE})
        await session.commit()
        left = (
            await session.execute(
                text("SELECT count(*) FROM coding_tasks WHERE task_id = :t"),
                {"t": task.task_id},
            )
        ).scalar_one()

    assert left == 0
