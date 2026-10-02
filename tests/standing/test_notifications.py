"""Q10b · Q3 owner notices: one contract in memory and in Postgres, and the drain.

The worker writes, the API process sends -- the channel adapters live only
there. A notice is written only when the agent has a target, once per dedupe
key, and its destination is fixed when it is written.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from neos.database.connection import db_manager
from neos.standing.notifications import (
    KIND_BUDGET_WARNING,
    KIND_QUESTION_CHANGED,
    InMemoryNotificationStore,
    NotifyTarget,
    PostgresNotificationStore,
    StandingNotice,
    StandingNotifier,
    bounded_body,
    build_standing_notifier,
    drain_once,
    gateway_send,
)
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore

ALICE = "test_q10b_notice_alice"
BOB = "test_q10b_notice_bob"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def _notice(agent_id, key="budget_warning:2026-10", body="hello"):
    return StandingNotice(agent_id=agent_id, kind=KIND_BUDGET_WARNING, dedupe_key=key, body=body)


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


class MemoryWorld:
    def __init__(self) -> None:
        self.agents = InMemoryStandingAgentStore()
        self.store = InMemoryNotificationStore()

    async def agent(self, owner):
        agent = await self.agents.create(owner, "Dot")
        self.store.agents[agent.agent_id] = owner
        return agent.agent_id

    async def row(self, agent_id):
        [row] = [row for row in self.store.rows.values() if row["agent_id"] == agent_id]
        return row


class PostgresWorld:
    def __init__(self) -> None:
        self.agents = PostgresStandingAgentStore(db_manager.get_session)
        self.store = PostgresNotificationStore(db_manager.get_session)

    async def agent(self, owner):
        async with await db_manager.get_session() as session:
            await session.execute(
                text("DELETE FROM standing_agents WHERE owner_id = :o"), {"o": owner}
            )
            await session.commit()
        return (await self.agents.create(owner, "Dot")).agent_id

    async def row(self, agent_id):
        async with await db_manager.get_session() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT kind, dedupe_key, channel_type, channel_id, body, status, "
                        "attempts, next_attempt_at, last_error, sent_at "
                        "FROM standing_notifications WHERE agent_id = :a"
                    ),
                    {"a": agent_id},
                )
            ).one()
        return dict(row._mapping)


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


@pytest.mark.asyncio
async def test_no_target_no_notice(world) -> None:
    agent_id = await world.agent(ALICE)

    assert await world.store.enqueue(_notice(agent_id), now=NOW) is False
    claimed = await world.store.claim_due(limit=500, now=NOW)
    assert all(notice.agent_id != agent_id for notice in claimed)


@pytest.mark.asyncio
async def test_a_notice_never_borrows_another_agents_target(world) -> None:
    """Bob's agent has a target; Alice's has none. Alice's notice goes nowhere --
    not to Bob's channel."""
    alice = await world.agent(ALICE)
    bob = await world.agent(BOB)
    await world.store.set_target(BOB, bob, NotifyTarget("slack", "BOBS-CHANNEL"))

    assert await world.store.enqueue(_notice(alice, body="for alice"), now=NOW) is False

    claimed = await world.store.claim_due(limit=500, now=NOW)
    assert all(notice.body != "for alice" for notice in claimed)
    assert all(notice.agent_id != alice for notice in claimed)


@pytest.mark.asyncio
async def test_a_target_belongs_to_the_owner(world) -> None:
    agent_id = await world.agent(ALICE)
    target = NotifyTarget("slack", "C1")

    assert await world.store.set_target(BOB, agent_id, target) is False
    assert await world.store.get_target(BOB, agent_id) is None
    assert await world.store.set_target(ALICE, agent_id, target) is True
    assert await world.store.get_target(ALICE, agent_id) == target
    assert await world.store.get_target(BOB, agent_id) is None
    assert await world.store.clear_target(BOB, agent_id) is False
    assert await world.store.clear_target(ALICE, agent_id) is True
    assert await world.store.get_target(ALICE, agent_id) is None


@pytest.mark.asyncio
async def test_once_per_dedupe_key_and_the_destination_is_fixed_when_written(world) -> None:
    agent_id = await world.agent(ALICE)
    await world.store.set_target(ALICE, agent_id, NotifyTarget("slack", "C1"))

    assert await world.store.enqueue(_notice(agent_id), now=NOW) is True
    await world.store.set_target(ALICE, agent_id, NotifyTarget("telegram", "42"))
    assert await world.store.enqueue(_notice(agent_id, body="again"), now=NOW) is False

    row = await world.row(agent_id)
    assert (row["channel_type"], row["channel_id"], row["body"]) == ("slack", "C1", "hello")
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_claim_send_and_retry(world) -> None:
    agent_id = await world.agent(ALICE)
    await world.store.set_target(ALICE, agent_id, NotifyTarget("slack", "C1"))
    await world.store.enqueue(_notice(agent_id), now=NOW)
    sent = []
    attempts = {"n": 0}

    async def flaky(channel_type, channel_id, body):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("slack down")
        sent.append((channel_type, channel_id, body))

    first = await drain_once(world.store, flaky, batch_size=50, max_attempts=3, now=NOW)
    row = await world.row(agent_id)
    assert first == 0
    assert row["status"] == "pending" and row["attempts"] == 1
    assert "slack down" in row["last_error"]
    # Not due again yet.
    assert await drain_once(world.store, flaky, batch_size=50, max_attempts=3, now=NOW) == 0

    later = NOW + timedelta(minutes=10)
    assert await drain_once(world.store, flaky, batch_size=50, max_attempts=3, now=later) == 1
    row = await world.row(agent_id)
    assert row["status"] == "sent" and row["attempts"] == 2
    assert sent == [("slack", "C1", "hello")]
    assert await drain_once(world.store, flaky, batch_size=50, max_attempts=3, now=later) == 0


@pytest.mark.asyncio
async def test_it_gives_up_after_max_attempts(world) -> None:
    agent_id = await world.agent(ALICE)
    await world.store.set_target(ALICE, agent_id, NotifyTarget("discord", "D1"))
    await world.store.enqueue(_notice(agent_id), now=NOW)

    async def down(channel_type, channel_id, body):
        raise RuntimeError("down")

    when = NOW
    for _ in range(2):
        await drain_once(world.store, down, batch_size=50, max_attempts=2, now=when)
        when += timedelta(hours=2)

    row = await world.row(agent_id)
    assert row["status"] == "failed" and row["attempts"] == 2
    assert await drain_once(world.store, down, batch_size=50, max_attempts=2, now=when) == 0


@pytest.mark.asyncio
async def test_a_claimed_notice_is_not_claimed_twice() -> None:
    """Two API workers draining at once must not both send it (Postgres: SKIP LOCKED + lease)."""
    await _seed_users()
    world = PostgresWorld()
    agent_id = await world.agent(ALICE)
    await world.store.set_target(ALICE, agent_id, NotifyTarget("slack", "C1"))
    await world.store.enqueue(_notice(agent_id), now=NOW)

    first = await world.store.claim_due(limit=50, now=NOW)
    second = await world.store.claim_due(limit=50, now=NOW)

    assert [notice.agent_id for notice in first].count(agent_id) == 1
    assert all(notice.agent_id != agent_id for notice in second)


@pytest.mark.asyncio
async def test_deleting_the_owner_is_not_blocked_by_notices() -> None:
    await _seed_users()
    world = PostgresWorld()
    agent_id = await world.agent(BOB)
    await world.store.set_target(BOB, agent_id, NotifyTarget("slack", "C1"))
    await world.store.enqueue(_notice(agent_id), now=NOW)

    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": BOB})
        await session.commit()
        left = (
            await session.execute(
                text("SELECT count(*) FROM standing_notifications WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()
    assert left == 0


@pytest.mark.asyncio
async def test_the_notifier_bounds_the_body_and_swallows_failures() -> None:
    store = InMemoryNotificationStore({"sa_1": ALICE})
    store.targets["sa_1"] = NotifyTarget("slack", "C1")
    notifier = StandingNotifier(store, max_body_chars=200, clock=lambda: NOW)

    assert await notifier.notify(_notice("sa_1", body="x" * 1_000)) is True
    [row] = store.rows.values()
    assert len(row["body"]) == 200 and row["body"].endswith("(잘림)")

    class Broken(InMemoryNotificationStore):
        async def enqueue(self, notice, *, now):
            raise RuntimeError("db down")

    assert await StandingNotifier(Broken(), max_body_chars=200).notify(_notice("sa_1")) is False


def test_bounded_body_leaves_short_bodies_alone() -> None:
    assert bounded_body("short", 200) == "short"


def test_notices_and_targets_are_closed_vocabularies() -> None:
    with pytest.raises(ValueError):
        StandingNotice(agent_id="sa_1", kind="anything", dedupe_key="k", body="b")
    with pytest.raises(ValueError):
        StandingNotice(agent_id="sa_1", kind=KIND_QUESTION_CHANGED, dedupe_key="", body="b")
    with pytest.raises(ValueError):
        NotifyTarget("email", "a@b.c")
    with pytest.raises(ValueError):
        NotifyTarget("slack", "  ")


@pytest.mark.asyncio
async def test_without_an_adapter_sending_is_a_failure_not_a_silent_success(monkeypatch) -> None:
    from neos.api.channels.gateway import ChannelGateway

    sent = []

    class Gateway:
        def has_adapter(self, channel_type):
            return channel_type == "slack"

        async def send_to_channel(self, channel_type, channel_id, body):
            sent.append((channel_type, channel_id, body))

    monkeypatch.setattr(ChannelGateway, "_INSTANCE", Gateway())
    await gateway_send("slack", "C1", "hi")
    with pytest.raises(RuntimeError, match="no channel adapter"):
        await gateway_send("telegram", "42", "hi")
    assert sent == [("slack", "C1", "hi")]

    monkeypatch.setattr(ChannelGateway, "_INSTANCE", None)
    with pytest.raises(RuntimeError):
        await gateway_send("slack", "C1", "hi")


def test_off_means_no_notifier() -> None:
    from neos.config.schema import StandingAgentsConfig

    assert build_standing_notifier(StandingAgentsConfig(), lambda: None) is None
    assert (
        build_standing_notifier(
            StandingAgentsConfig(enabled=True, notifications={"enabled": False}), lambda: None
        )
        is None
    )
    assert (
        build_standing_notifier(
            StandingAgentsConfig(enabled=False, notifications={"enabled": True}), lambda: None
        )
        is None
    )
    assert isinstance(
        build_standing_notifier(
            StandingAgentsConfig(enabled=True, notifications={"enabled": True}), lambda: None
        ),
        StandingNotifier,
    )
