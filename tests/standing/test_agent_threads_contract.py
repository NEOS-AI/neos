"""Q8a: one contract, two stores, for the cross-channel agent thread.

The in-memory thread store and the Postgres thread store must answer the same
way (docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §10). The Postgres half runs
on the real `<name>_test` database; conftest deletes `test%@%` users before and
after, and agents, threads, sessions and turns go with them (ON DELETE CASCADE --
a missing cascade would make that cleanup fail, which is itself a check).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from neos.database.connection import db_manager
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore
from neos.standing.threads import (
    InMemoryAgentThreadStore,
    PostgresAgentThreadStore,
    resolve_agent_thread,
    rotate_agent_thread,
    thread_window,
)

ALICE = "test_threads_alice"
BOB = "test_threads_bob"
SLACK_DM = "v2:slack:T1:D1:-"
TELEGRAM_DM = "v2:telegram:dm:42:-"


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


@pytest.fixture(params=["memory", "postgres"])
async def stores(request):
    if request.param == "memory":
        agents = InMemoryStandingAgentStore()
        return agents, InMemoryAgentThreadStore(agents)
    await _seed_users()
    return (
        PostgresStandingAgentStore(db_manager.get_session),
        PostgresAgentThreadStore(db_manager.get_session),
    )


async def _agent(agents, owner: str = ALICE):
    return await agents.create(owner, f"Dot-{owner}")


# ---- the active thread ------------------------------------------------------


@pytest.mark.asyncio
async def test_an_agent_gets_one_active_thread(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)

    first = await resolve_agent_thread(threads, agent)
    again = await resolve_agent_thread(threads, agent)

    assert first is not None and first.agent_thread_id.startswith("sat_")
    assert first.agent_id == agent.agent_id
    assert first.archived_at is None
    assert again == first


@pytest.mark.asyncio
async def test_concurrent_first_reads_share_one_thread(stores) -> None:
    """The "one" lives in one partial index: a loser re-reads the winner."""
    agents, threads = stores
    agent = await _agent(agents)

    results = await asyncio.gather(*(resolve_agent_thread(threads, agent) for _ in range(5)))

    assert len({thread.agent_thread_id for thread in results}) == 1
    assert len(await threads.list_threads(agent.agent_id)) == 1


@pytest.mark.asyncio
async def test_two_agents_have_separate_threads(stores) -> None:
    agents, threads = stores
    alice = await resolve_agent_thread(threads, await _agent(agents, ALICE))
    bob = await resolve_agent_thread(threads, await _agent(agents, BOB))

    assert alice.agent_thread_id != bob.agent_thread_id


# ---- sessions -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_attach_to_the_active_thread(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)

    via_slack = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    via_telegram = await threads.attach_session(agent.agent_id, TELEGRAM_DM, "telegram")

    assert via_slack == via_telegram == await resolve_agent_thread(threads, agent)
    assert await threads.thread_for_session(SLACK_DM) == via_slack
    assert await threads.thread_for_session("v2:slack:T1:D9:-") is None


@pytest.mark.asyncio
async def test_attaching_twice_is_one_row(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)

    first = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    second = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    assert first == second
    assert [s.session_id for s in await threads.list_sessions(first.agent_thread_id)] == [SLACK_DM]


@pytest.mark.asyncio
async def test_a_session_attached_to_one_agent_is_not_taken_by_another(stores) -> None:
    """A session belongs to one thread. Another agent asking for it gets None, and
    the first agent keeps it -- no silent move across owners."""
    agents, threads = stores
    alice = await _agent(agents, ALICE)
    bob = await _agent(agents, BOB)
    owned = await threads.attach_session(alice.agent_id, SLACK_DM, "slack")

    assert await threads.attach_session(bob.agent_id, SLACK_DM, "slack") is None
    assert await threads.thread_for_session(SLACK_DM) == owned


@pytest.mark.asyncio
async def test_unknown_channel_types_are_refused(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)

    with pytest.raises(ValueError):
        await threads.attach_session(agent.agent_id, "v2:irc:x:y:-", "irc")


# ---- turns and the window -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_window_is_the_newest_turns_oldest_first(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    for index in range(5):
        await threads.append_turn(
            thread.agent_thread_id, SLACK_DM, "slack", "user", f"turn {index}"
        )

    window = await thread_window(threads, thread.agent_thread_id, limit=3)

    assert [turn.content for turn in window] == ["turn 2", "turn 3", "turn 4"]
    assert all(turn.channel_type == "slack" and turn.role == "user" for turn in window)
    assert await thread_window(threads, thread.agent_thread_id, limit=0) == []


@pytest.mark.asyncio
async def test_turns_from_two_channels_share_one_window(stores) -> None:
    """F10: what was said on Slack is in the next Telegram turn's window."""
    agents, threads = stores
    agent = await _agent(agents)
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await threads.attach_session(agent.agent_id, TELEGRAM_DM, "telegram")

    await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "user", "on slack")
    await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "assistant", "ok")
    await threads.append_turn(
        thread.agent_thread_id, TELEGRAM_DM, "telegram", "user", "on telegram"
    )

    window = await thread_window(threads, thread.agent_thread_id, limit=10)
    assert [(t.channel_type, t.role, t.content) for t in window] == [
        ("slack", "user", "on slack"),
        ("slack", "assistant", "ok"),
        ("telegram", "user", "on telegram"),
    ]


@pytest.mark.asyncio
async def test_the_same_idem_key_writes_one_turn(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    wrote = await threads.append_turn(
        thread.agent_thread_id, SLACK_DM, "slack", "user", "hi", idem_key="m1"
    )
    again = await threads.append_turn(
        thread.agent_thread_id, SLACK_DM, "slack", "user", "hi", idem_key="m1"
    )
    # The reply to the same inbound message is a different role -- not a duplicate.
    reply = await threads.append_turn(
        thread.agent_thread_id, SLACK_DM, "slack", "assistant", "hello", idem_key="m1"
    )

    assert (wrote, again, reply) == (True, False, True)
    assert len(await thread_window(threads, thread.agent_thread_id, limit=10)) == 2


@pytest.mark.asyncio
async def test_turns_without_an_idem_key_are_never_merged(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    for _ in range(2):
        assert await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "user", "x")

    assert len(await thread_window(threads, thread.agent_thread_id, limit=10)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "content"), [("system", "x"), ("reset", "x"), ("user", "   ")]
)
async def test_bad_turns_are_refused(stores, role: str, content: str) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    with pytest.raises(ValueError):
        await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", role, content)


# ---- rotation (decision Q8-2) ----------------------------------------------------


@pytest.mark.asyncio
async def test_rotation_archives_opens_and_moves_every_session(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    old = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await threads.attach_session(agent.agent_id, TELEGRAM_DM, "telegram")
    await threads.append_turn(old.agent_thread_id, SLACK_DM, "slack", "user", "before")

    new = await rotate_agent_thread(threads, agent)

    assert new.agent_thread_id != old.agent_thread_id and new.archived_at is None
    assert await resolve_agent_thread(threads, agent) == new
    # Sessions stay attached -- moved, not dropped.
    assert await threads.thread_for_session(SLACK_DM) == new
    assert await threads.thread_for_session(TELEGRAM_DM) == new
    # The new window is empty; the old transcript is kept (archived, read-only).
    assert await thread_window(threads, new.agent_thread_id, limit=10) == []
    assert [t.content for t in await thread_window(threads, old.agent_thread_id, limit=10)] == [
        "before"
    ]
    listed = await threads.list_threads(agent.agent_id)
    assert [(t.agent_thread_id, t.archived_at is None) for t in listed] == [
        (old.agent_thread_id, False),
        (new.agent_thread_id, True),
    ]


@pytest.mark.asyncio
async def test_rotation_without_a_thread_opens_one(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)

    opened = await rotate_agent_thread(threads, agent)

    assert await resolve_agent_thread(threads, agent) == opened
    assert len(await threads.list_threads(agent.agent_id)) == 1


@pytest.mark.asyncio
async def test_concurrent_rotations_rotate_once(stores) -> None:
    """Two `/new` at once: the partial index lets one through, the other re-reads."""
    agents, threads = stores
    agent = await _agent(agents)
    await threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    results = await asyncio.gather(*(rotate_agent_thread(threads, agent) for _ in range(4)))

    active = await resolve_agent_thread(threads, agent)
    assert len({thread.agent_thread_id for thread in results}) >= 1
    assert active.agent_thread_id in {thread.agent_thread_id for thread in results}
    assert sum(t.archived_at is None for t in await threads.list_threads(agent.agent_id)) == 1
    assert await threads.thread_for_session(SLACK_DM) == active


# ---- deletion (decision Q8-4) and ownership ---------------------------------------


@pytest.mark.asyncio
async def test_deleting_the_agent_deletes_threads_sessions_and_turns(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    old = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await threads.append_turn(old.agent_thread_id, SLACK_DM, "slack", "user", "secret plan")
    new = await rotate_agent_thread(threads, agent)
    await threads.append_turn(new.agent_thread_id, SLACK_DM, "slack", "user", "more")

    assert await agents.delete(ALICE, agent.agent_id) is True

    assert await threads.list_threads(agent.agent_id) == []
    assert await threads.thread_for_session(SLACK_DM) is None
    for thread in (old, new):
        assert await thread_window(threads, thread.agent_thread_id, limit=10) == []
        assert await threads.list_sessions(thread.agent_thread_id) == []


@pytest.mark.asyncio
async def test_a_deleted_agent_gets_no_thread(stores) -> None:
    agents, threads = stores
    agent = await _agent(agents)
    await agents.delete(ALICE, agent.agent_id)

    assert await resolve_agent_thread(threads, agent) is None
    assert await threads.attach_session(agent.agent_id, SLACK_DM, "slack") is None
    assert await rotate_agent_thread(threads, agent) is None


@pytest.mark.asyncio
async def test_after_delete_the_session_may_attach_to_a_new_agent(stores) -> None:
    agents, threads = stores
    first = await _agent(agents)
    await threads.attach_session(first.agent_id, SLACK_DM, "slack")
    await agents.delete(ALICE, first.agent_id)

    second = await agents.create(ALICE, "Dot again")
    attached = await threads.attach_session(second.agent_id, SLACK_DM, "slack")

    assert attached is not None and attached.agent_id == second.agent_id


# ---- Postgres only ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_the_user_removes_everything_in_one_statement() -> None:
    """The cascade chain users -> standing_agents -> threads -> sessions/turns must be
    unbroken; a NO ACTION link would make this DELETE fail."""
    await _seed_users()
    agents = PostgresStandingAgentStore(db_manager.get_session)
    threads = PostgresAgentThreadStore(db_manager.get_session)
    agent = await agents.create(BOB, "Dot")
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "user", "hi")

    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": BOB})
        await session.commit()
        remaining = await session.execute(
            text(
                "SELECT (SELECT count(*) FROM standing_agent_threads WHERE agent_id = :a)"
                " + (SELECT count(*) FROM standing_agent_thread_sessions WHERE session_id = :s)"
                " + (SELECT count(*) FROM standing_agent_thread_turns"
                "    WHERE agent_thread_id = :t)"
            ),
            {"a": agent.agent_id, "s": SLACK_DM, "t": thread.agent_thread_id},
        )
        assert remaining.scalar_one() == 0


@pytest.mark.asyncio
async def test_turns_carry_the_writing_transaction_id() -> None:
    """Q8c's feed cursor needs `xact_id` on every row from the first write."""
    await _seed_users()
    agents = PostgresStandingAgentStore(db_manager.get_session)
    threads = PostgresAgentThreadStore(db_manager.get_session)
    agent = await agents.create(ALICE, "Dot")
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "user", "hi")

    async with await db_manager.get_session() as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM standing_agent_thread_turns"
                " WHERE agent_thread_id = :t AND xact_id IS NOT NULL"
            ),
            {"t": thread.agent_thread_id},
        )
        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_a_session_left_on_an_archived_thread_moves_to_the_active_one() -> None:
    """A rotation racing an attach can leave the session row on the thread it just
    archived. The next attach must hand back the active thread, not the archived one."""
    await _seed_users()
    agents = PostgresStandingAgentStore(db_manager.get_session)
    threads = PostgresAgentThreadStore(db_manager.get_session)
    agent = await agents.create(ALICE, "Dot")
    old = await resolve_agent_thread(threads, agent)
    new = await rotate_agent_thread(threads, agent)
    # Plant the race's outcome: the session row points at the archived thread.
    async with await db_manager.get_session() as session:
        await session.execute(
            text(
                "INSERT INTO standing_agent_thread_sessions"
                " (session_id, agent_thread_id, channel_type) VALUES (:s, :t, 'slack')"
            ),
            {"s": SLACK_DM, "t": old.agent_thread_id},
        )
        await session.commit()
    assert await threads.thread_for_session(SLACK_DM) is None

    attached = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    assert attached == new
    assert await threads.thread_for_session(SLACK_DM) == new
