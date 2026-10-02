"""Q13a: one contract, two stores. The in-memory store and the Postgres store
must answer the same way -- otherwise the unit tests describe a system that
does not exist.

Real database for the Postgres half: conftest builds `<name>_test` from the
migrations and deletes `test%@%` users before and after; agents go with them
(ON DELETE CASCADE).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from neos.database.connection import db_manager
from neos.standing.models import StandingAgentConflict, StandingAgentStatus
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore

ALICE = "test_standing_alice"
BOB = "test_standing_bob"


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
async def store(request):
    if request.param == "memory":
        return InMemoryStandingAgentStore()
    await _seed_users()
    return PostgresStandingAgentStore(db_manager.get_session)


@pytest.mark.asyncio
async def test_a_new_agent_is_active_and_named(store) -> None:
    agent = await store.create(ALICE, "  Dot ")

    assert agent.agent_id.startswith("sa_")
    assert agent.owner_id == ALICE
    assert agent.name == "Dot"
    assert agent.status is StandingAgentStatus.ACTIVE


@pytest.mark.asyncio
async def test_one_agent_per_owner(store) -> None:
    """Decision 6: the "one" lives in one index."""
    await store.create(ALICE, "Dot")

    with pytest.raises(StandingAgentConflict) as raised:
        await store.create(ALICE, "Other")
    assert raised.value.reason == "one_per_owner"


@pytest.mark.asyncio
async def test_after_a_delete_the_owner_may_create_again(store) -> None:
    first = await store.create(ALICE, "Dot")
    assert await store.delete(ALICE, first.agent_id) is True

    second = await store.create(ALICE, "Dot")

    assert second.agent_id != first.agent_id


@pytest.mark.asyncio
async def test_two_owners_may_use_the_same_name(store) -> None:
    """Uniqueness is per owner -- global uniqueness would reveal others' names."""
    await store.create(ALICE, "Dot")

    assert (await store.create(BOB, "dot")).name == "dot"


@pytest.mark.asyncio
async def test_someone_elses_agent_is_indistinguishable_from_none(store) -> None:
    agent = await store.create(ALICE, "Dot")

    assert await store.get_owned(BOB, agent.agent_id) is None
    assert await store.get_owned(BOB, "sa_missing") is None
    assert await store.delete(BOB, agent.agent_id) is False
    assert (await store.get_owned(ALICE, agent.agent_id)).agent_id == agent.agent_id


@pytest.mark.asyncio
async def test_a_deleted_agent_is_gone_from_reads(store) -> None:
    agent = await store.create(ALICE, "Dot")
    await store.delete(ALICE, agent.agent_id)

    assert await store.get_owned(ALICE, agent.agent_id) is None
    assert await store.list_for_owner(ALICE) == []


@pytest.mark.asyncio
async def test_the_list_is_the_owners_only(store) -> None:
    mine = await store.create(ALICE, "Dot")
    await store.create(BOB, "Bob's")

    assert [agent.agent_id for agent in await store.list_for_owner(ALICE)] == [mine.agent_id]


@pytest.mark.asyncio
async def test_a_very_long_name_is_stored(store) -> None:
    """No length limit (decision 3) -- the name index is on a hash, not the text."""
    name = "d" * 10_000

    assert (await store.create(ALICE, name)).name == name


@pytest.mark.asyncio
async def test_the_name_index_refuses_a_duplicate_once_many_are_allowed() -> None:
    """The name rule must already hold for the day the one-per-owner index is
    dropped. Drop it inside a transaction, try, roll back."""
    await _seed_users()
    async with await db_manager.get_session() as session:
        transaction = await session.begin()
        try:
            await session.execute(text("DROP INDEX uq_standing_agents_one_per_owner"))
            insert = text(
                "INSERT INTO standing_agents (agent_id, owner_id, name) VALUES (:a, :o, :n)"
            )
            await session.execute(insert, {"a": "sa_t1", "o": ALICE, "n": "Dot"})
            with pytest.raises(IntegrityError) as raised:
                await session.execute(insert, {"a": "sa_t2", "o": ALICE, "n": "  dOT "})
            assert "uq_standing_agents_name_per_owner" in str(raised.value)
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_update_renames_and_changes_status(store) -> None:
    agent = await store.create(ALICE, "Dot")

    renamed = await store.update(ALICE, agent.agent_id, name="  Dotty ")
    paused = await store.update(ALICE, agent.agent_id, status=StandingAgentStatus.PAUSED)

    assert renamed.name == "Dotty"
    assert paused.name == "Dotty"
    assert paused.status is StandingAgentStatus.PAUSED
    assert (await store.get_owned(ALICE, agent.agent_id)).status is StandingAgentStatus.PAUSED


@pytest.mark.asyncio
async def test_update_of_someone_elses_agent_is_none(store) -> None:
    agent = await store.create(ALICE, "Dot")

    assert await store.update(BOB, agent.agent_id, name="Mine") is None
    assert (await store.get_owned(ALICE, agent.agent_id)).name == "Dot"


@pytest.mark.asyncio
async def test_update_refuses_an_empty_name(store) -> None:
    agent = await store.create(ALICE, "Dot")

    with pytest.raises(ValueError):
        await store.update(ALICE, agent.agent_id, name="   ")


@pytest.mark.asyncio
async def test_a_retired_agent_still_holds_the_one_slot(store) -> None:
    """Both indexes see only `deleted_at IS NULL` -- retire is not delete."""
    agent = await store.create(ALICE, "Dot")
    await store.update(ALICE, agent.agent_id, status=StandingAgentStatus.RETIRED)

    with pytest.raises(StandingAgentConflict):
        await store.create(ALICE, "Another")


# -- Q13f: the self-introduction ------------------------------------------------


@pytest.mark.asyncio
async def test_the_onboarding_task_is_set_once(store) -> None:
    agent = await store.create(ALICE, "Dot")

    assert await store.set_onboarding_task(ALICE, agent.agent_id, "ct_1") is True
    assert await store.set_onboarding_task(ALICE, agent.agent_id, "ct_2") is False
    assert (await store.get_owned(ALICE, agent.agent_id)).onboarding_task_id == "ct_1"


@pytest.mark.asyncio
async def test_onboarded_is_claimed_once_and_only_for_that_task(store) -> None:
    agent = await store.create(ALICE, "Dot")
    await store.set_onboarding_task(ALICE, agent.agent_id, "ct_1")

    assert await store.claim_onboarded(ALICE, agent.agent_id, "ct_other") is False
    assert await store.claim_onboarded(ALICE, agent.agent_id, "ct_1") is True
    assert await store.claim_onboarded(ALICE, agent.agent_id, "ct_1") is False
    assert (await store.get_owned(ALICE, agent.agent_id)).onboarded_at is not None


@pytest.mark.asyncio
async def test_nothing_is_claimed_before_an_onboarding_task_exists(store) -> None:
    agent = await store.create(ALICE, "Dot")

    assert await store.claim_onboarded(ALICE, agent.agent_id, "ct_1") is False


@pytest.mark.asyncio
async def test_someone_else_cannot_set_or_claim(store) -> None:
    agent = await store.create(ALICE, "Dot")

    assert await store.set_onboarding_task(BOB, agent.agent_id, "ct_1") is False
    await store.set_onboarding_task(ALICE, agent.agent_id, "ct_1")
    assert await store.claim_onboarded(BOB, agent.agent_id, "ct_1") is False
