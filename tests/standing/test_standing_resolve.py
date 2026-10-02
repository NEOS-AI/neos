"""Q13 §6: every caller finds its agent through `resolve_agent`.

API, channel gateway and scheduler all go through it -- two lookups would
diverge the day an owner may have many.
"""

from __future__ import annotations

import pytest

from neos.standing.resolve import resolve_agent
from neos.standing.store import InMemoryStandingAgentStore

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_no_agent_resolves_to_none() -> None:
    assert await resolve_agent(InMemoryStandingAgentStore(), "alice") is None


@pytest.mark.asyncio
async def test_without_an_id_the_owners_only_agent_is_found() -> None:
    store = InMemoryStandingAgentStore()
    agent = await store.create("alice", "Dot")

    assert (await resolve_agent(store, "alice")).agent_id == agent.agent_id


@pytest.mark.asyncio
async def test_with_an_id_only_the_owner_finds_it() -> None:
    store = InMemoryStandingAgentStore()
    agent = await store.create("alice", "Dot")

    assert (await resolve_agent(store, "alice", agent.agent_id)).agent_id == agent.agent_id
    assert await resolve_agent(store, "bob", agent.agent_id) is None


@pytest.mark.asyncio
async def test_a_wrong_id_does_not_fall_back_to_the_owners_agent() -> None:
    """An explicit id is never "close enough". Once owners may have several
    agents, a fallback here would hand the work to the wrong one."""
    store = InMemoryStandingAgentStore()
    await store.create("alice", "Dot")

    assert await resolve_agent(store, "alice", "sa_missing") is None
