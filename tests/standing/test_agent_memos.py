"""Q13e: a standing agent's memos (design §8, dots F7 and F18).

Memos are STAGED only -- whatever `learn.write_approval` says. The existing
`maybe_learn_ltm` writes straight to long-term memory when that switch is off,
so the agent path has its own staged-only door; both switch positions are run.
Memos are not training data: they live in `agent:{id}`, which the owner-keyed
injection never reads and which cannot own a GEPA run.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.learn.lessons import (
    LessonStatus,
    reset_lesson_store,
    set_lesson_session_factory,
)
from neos.learn.policy import agent_namespace, is_agent_namespace, namespace
from neos.learn.postgres import PostgresLessonStore
from neos.standing.memos import MEMO_KIND, AgentMemoRefused, write_agent_memo
from neos.standing.models import StandingAgentStatus
from neos.standing.store import InMemoryStandingAgentStore

ALICE = "alice"
BOB = "bob"


@pytest.fixture(params=["memory", "postgres"])
async def lessons(request):
    """Where memos land, and a reader for them. The Postgres rows are removed
    afterwards -- `learned_lessons` has no user FK for conftest to cascade."""
    if request.param == "memory":
        store = reset_lesson_store()

        async def read(ns):
            return store.list(ns)

        yield read
        reset_lesson_store()
        return
    set_lesson_session_factory(db_manager.get_session)
    store = PostgresLessonStore(db_manager.get_session)
    written: list[str] = []

    async def read(ns):
        written.append(ns)
        return await store.list(ns)

    yield read
    async with await db_manager.get_session() as session:
        await session.execute(
            text("DELETE FROM learned_lessons WHERE namespace LIKE 'agent:sa_%' AND kind = :k"),
            {"k": MEMO_KIND},
        )
        await session.commit()
    reset_lesson_store()


@pytest.fixture
def agents():
    return InMemoryStandingAgentStore()


@pytest.fixture
def learn(monkeypatch):
    spy = AsyncMock(return_value=True)
    monkeypatch.setattr("neos.memory.manager.memory_manager.learn", spy)
    return spy


@pytest.mark.asyncio
@pytest.mark.parametrize("write_approval", [True, False])
async def test_a_memo_is_staged_whatever_write_approval_says(
    agents, lessons, learn, monkeypatch, write_approval
) -> None:
    """Mutation: route through `maybe_learn_ltm` -> with the switch off the memo
    goes straight to long-term memory."""
    monkeypatch.setattr(settings.config.learn, "write_approval", write_approval)
    agent = await agents.create(ALICE, "Dot")

    memo = await write_agent_memo(agents, owner_id=ALICE, body="The repo uses uv.")

    stored = await lessons(agent_namespace(agent.agent_id))
    assert [(m.lesson_id, m.status, m.kind) for m in stored] == [
        (memo.lesson_id, LessonStatus.STAGED, "agent_memo")
    ]  # the literal, not MEMO_KIND: a changed constant must fail here
    assert stored[0].body == "The repo uses uv."
    learn.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_memo_is_the_agents_not_the_owners(agents, lessons, learn) -> None:
    agent = await agents.create(ALICE, "Dot")

    memo = await write_agent_memo(agents, owner_id=ALICE, body="note", title="  First  ")

    assert memo.namespace == f"agent:{agent.agent_id}"
    assert memo.title == "First"
    assert await lessons(namespace(ALICE)) == ()


@pytest.mark.asyncio
async def test_someone_elses_agent_writes_nothing(agents, lessons, learn) -> None:
    await agents.create(ALICE, "Dot")
    bobs = await agents.create(BOB, "Bobby")

    with pytest.raises(AgentMemoRefused) as raised:
        await write_agent_memo(agents, owner_id=ALICE, body="x", agent_id=bobs.agent_id)

    assert raised.value.reason == "agent_not_found"
    assert await lessons(agent_namespace(bobs.agent_id)) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "reason"),
    [("   ", "empty"), ("Always run the tests first.", "imperative")],
)
async def test_what_a_memo_may_not_be(agents, lessons, learn, body, reason) -> None:
    agent = await agents.create(ALICE, "Dot")

    with pytest.raises(AgentMemoRefused) as raised:
        await write_agent_memo(agents, owner_id=ALICE, body=body)

    assert raised.value.reason == reason
    assert await lessons(agent_namespace(agent.agent_id)) == ()


@pytest.mark.asyncio
async def test_a_paused_agents_running_work_may_still_leave_a_memo(
    agents, lessons, learn
) -> None:
    """Decision 2: pausing does not touch running tasks, so their memos land."""
    agent = await agents.create(ALICE, "Dot")
    await agents.update(ALICE, agent.agent_id, status=StandingAgentStatus.PAUSED)

    memo = await write_agent_memo(agents, owner_id=ALICE, body="found it")

    assert memo.status is LessonStatus.STAGED


# -- F18: not training data -------------------------------------------------


@pytest.mark.asyncio
async def test_even_an_approved_memo_never_reaches_the_owners_injection(
    agents, learn, monkeypatch
) -> None:
    """The coding lesson injection reads `owner:{id}` only. An approved agent
    memo must not be in what it returns."""
    from neos.coding.learn_lessons import _approved_lessons

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    agent = await agents.create(ALICE, "Dot")
    memo = await write_agent_memo(agents, owner_id=ALICE, body="agent note")
    store.update(replace(store.get(memo.lesson_id), status=LessonStatus.APPROVED))
    assert [m.status for m in store.list(agent_namespace(agent.agent_id))] == [
        LessonStatus.APPROVED
    ]

    assert await _approved_lessons(ALICE) == ()
    reset_lesson_store()


@pytest.mark.asyncio
async def test_an_agent_namespace_cannot_own_a_gepa_run() -> None:
    from neos.gepa_opt.store import GepaOptStore

    touched = []

    async def factory():
        touched.append(True)
        raise AssertionError("no session should be opened")

    with pytest.raises(ValueError):
        await GepaOptStore(factory).insert_run_with_seed(
            run_id="r", owner_namespace=agent_namespace("sa_1"), surface="coding_overlay",
            engine_label="gepa", pareto_enabled=False, max_evals=1, max_token_cost=1,
            seed_components={"instr": "a"}, examples=[],
        )
    assert touched == []


def test_the_namespace_predicate() -> None:
    assert is_agent_namespace(agent_namespace("sa_1"))
    assert not is_agent_namespace(namespace("sa_1"))
    assert not is_agent_namespace("")
    with pytest.raises(ValueError):
        agent_namespace("  ")
