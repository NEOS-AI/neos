"""Q10a: the standing agent budget envelope (design §3).

The envelope is agent x calendar month (UTC). Spend is not counted anywhere:
it is the latest checkpoint's cumulative `cost_micros` of every agent task
opened in the month. One contract runs over the in-memory source and the
Postgres source (real DB) -- the Postgres half writes real runs and
checkpoints and lets the query pick the latest one.

Real database for the Postgres half: conftest deletes `test%@%` users before
and after; agents, tasks, runs and checkpoints go with them (CASCADE).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.domain.models import CodingTaskMode
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.persistence.postgres import PostgresCodingService
from neos.database.connection import db_manager
from neos.standing.budget import (
    OVER_BACKGROUND_SHARE,
    OVER_ENVELOPE,
    OVER_HANDED_OVER_SHARE,
    AgentBudgetEnvelope,
    AgentSpend,
    InMemoryAgentSpendSource,
    PostgresAgentSpendSource,
    background_limit,
    build_agent_envelope,
    envelope_verdict,
    month_bounds,
)
from neos.standing.onboarding import start_onboarding
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore
from neos.standing.tasks import AgentTaskRefused, open_agent_task

ALICE = "test_agent_budget_alice"
BOB = "test_agent_budget_bob"
OCT = datetime(2026, 10, 1, tzinfo=UTC)
START = datetime(2026, 10, 1, tzinfo=UTC)


def _verdict(total, background=0, *, mode="background", limit=100, share=0.5, reserve=False):
    return envelope_verdict(
        AgentSpend(total_micros=total, background_micros=background),
        limit_micros=limit,
        background_share=share,
        mode=mode,
        period_start=START,
        reserve_background_share=reserve,
    )


# -- the verdict ----------------------------------------------------------------


def test_under_both_limits_is_not_over() -> None:
    verdict = _verdict(99, 49)

    assert not verdict.over
    assert verdict.reason is None


def test_touching_the_envelope_is_over() -> None:
    """Nothing left is over: a task opened with 0 left spends past it on turn one."""
    assert _verdict(100, 0, mode="autonomous").reason == OVER_ENVELOPE
    assert not _verdict(99, 0, mode="autonomous").over


def test_background_stops_at_its_share_but_handed_over_work_does_not() -> None:
    assert _verdict(60, 50, mode="background").reason == OVER_BACKGROUND_SHARE
    assert not _verdict(60, 49, mode="background").over
    assert not _verdict(60, 50, mode="autonomous").over


def test_the_whole_envelope_wins_over_the_share() -> None:
    assert _verdict(100, 50, mode="background").reason == OVER_ENVELOPE


def test_the_share_rounds_down() -> None:
    assert background_limit(101, 0.5) == 50
    assert background_limit(100, 1.0) == 100


def test_the_payload_can_recompute_the_verdict() -> None:
    payload = _verdict(100, 50, mode="background", limit=100, share=0.5).payload(
        mode="background"
    )

    assert payload == {
        "would_pause": True,
        "reason": OVER_ENVELOPE,
        "spent_micros": 100,
        "limit_micros": 100,
        "background_spent_micros": 50,
        "background_limit_micros": 50,
        "period_start": "2026-10-01T00:00:00+00:00",
        "reserve_background_share": False,
        "mode": "background",
        "enforced": False,
    }


# -- the reserved share (reserve_background_share) -------------------------------


def test_reserved_share_stops_handed_over_work_at_the_rest() -> None:
    """Limit 100, share 50 reserved: autonomous may spend 50 of its own, not the 50 kept for background."""
    assert _verdict(50, 0, mode="autonomous", reserve=True).reason == OVER_HANDED_OVER_SHARE
    assert not _verdict(49, 0, mode="autonomous", reserve=True).over


def test_reserved_share_counts_only_handed_over_spend_against_the_rest() -> None:
    """Background spend does not use up the autonomous part."""
    assert not _verdict(90, 45, mode="autonomous", reserve=True).over
    assert _verdict(95, 45, mode="autonomous", reserve=True).reason == OVER_HANDED_OVER_SHARE


def test_reserving_leaves_background_work_unchanged() -> None:
    assert not _verdict(90, 49, mode="background", reserve=True).over
    assert _verdict(60, 50, mode="background", reserve=True).reason == OVER_BACKGROUND_SHARE


def test_the_whole_envelope_still_wins_when_reserving() -> None:
    assert _verdict(100, 10, mode="autonomous", reserve=True).reason == OVER_ENVELOPE


def test_without_reserving_handed_over_work_may_eat_the_share() -> None:
    """Switched off, autonomous runs up to the whole envelope."""
    assert not _verdict(99, 0, mode="autonomous").over


def test_reserving_the_whole_envelope_leaves_nothing_for_handed_over_work() -> None:
    assert _verdict(0, 0, mode="autonomous", share=1.0, reserve=True).reason == OVER_HANDED_OVER_SHARE


def test_the_payload_says_whether_the_share_was_reserved() -> None:
    payload = _verdict(50, 0, mode="autonomous", reserve=True).payload(mode="autonomous")

    assert payload["reserve_background_share"] is True
    assert payload["reason"] == OVER_HANDED_OVER_SHARE


@pytest.mark.parametrize(
    ("now", "start", "end"),
    [
        (datetime(2026, 10, 17, 9, tzinfo=UTC), datetime(2026, 10, 1), datetime(2026, 11, 1)),
        (datetime(2026, 12, 31, 23, 59, tzinfo=UTC), datetime(2026, 12, 1), datetime(2027, 1, 1)),
        (datetime(2027, 1, 1, tzinfo=UTC), datetime(2027, 1, 1), datetime(2027, 2, 1)),
    ],
)
def test_the_period_is_the_utc_calendar_month(now, start, end) -> None:
    assert month_bounds(now) == (start.replace(tzinfo=UTC), end.replace(tzinfo=UTC))


def test_a_local_clock_is_read_in_utc() -> None:
    """01:00 on Nov 1 in Seoul is still October in UTC."""
    from zoneinfo import ZoneInfo

    seoul = datetime(2026, 11, 1, 1, tzinfo=ZoneInfo("Asia/Seoul"))

    assert month_bounds(seoul)[0] == datetime(2026, 10, 1, tzinfo=UTC)


def test_off_builds_no_envelope() -> None:
    from neos.config.schema import StandingAgentsConfig

    assert build_agent_envelope(StandingAgentsConfig(), lambda: None) is None
    on = StandingAgentsConfig(budget={"enabled": True, "monthly_limit_micros": 7})
    assert isinstance(build_agent_envelope(on, lambda: None), AgentBudgetEnvelope)
    assert StandingAgentsConfig().budget.reserve_background_share is True


@pytest.mark.asyncio
async def test_the_setting_reaches_the_verdict() -> None:
    """The factory carries reserve_background_share into the envelope it builds --
    switched off here, against the default, so a factory that drops it fails."""
    from neos.config.schema import StandingAgentsConfig

    class Fixed:
        async def spent(self, *_args):
            return AgentSpend(total_micros=50, background_micros=0)

    config = StandingAgentsConfig(
        budget={"enabled": True, "monthly_limit_micros": 100, "reserve_background_share": False}
    )
    envelope = build_agent_envelope(config, lambda: None)
    envelope._source = Fixed()

    assert not (await envelope.judge("sa_1", "autonomous")).over


# -- the spend source: one contract, two sources --------------------------------


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


class PostgresWorld:
    """Writes real tasks, runs and checkpoints; spend comes back through SQL."""

    def __init__(self) -> None:
        self.agents = PostgresStandingAgentStore(db_manager.get_session)
        self.coding = PostgresCodingService(db_manager.get_session)
        self.source = PostgresAgentSpendSource(db_manager.get_session)

    async def task(self, *, owner, agent_id, mode, created_at, costs):
        task = await self.coding.create_task(
            owner_id=owner, prompt="p", mode=CodingTaskMode(mode), agent_id=agent_id
        )
        async with await db_manager.get_session() as session:
            await session.execute(
                text("UPDATE coding_tasks SET created_at = :at WHERE task_id = :t"),
                {"at": created_at, "t": task.task_id},
            )
            run_id = f"cr_{uuid4().hex}"
            await session.execute(
                text(
                    "INSERT INTO coding_runs (run_id, task_id, attempt, status, started_at) "
                    "VALUES (:r, :t, 1, 'running', :at)"
                ),
                {"r": run_id, "t": task.task_id, "at": created_at},
            )
            # Written out of seq order: the query must pick by seq, not by insert order.
            for seq, cost in sorted(enumerate(costs, start=1), key=lambda pair: -pair[0]):
                await session.execute(
                    text(
                        "INSERT INTO coding_checkpoints (checkpoint_id, task_id, run_id, seq, "
                        "loop_state_json, workspace_revision, created_at) "
                        "VALUES (:c, :t, :r, :s, CAST(:state AS JSONB), 'rev', :at)"
                    ),
                    {
                        "c": f"ck_{uuid4().hex}",
                        "t": task.task_id,
                        "r": run_id,
                        "s": seq,
                        "state": json.dumps({"cost_micros": cost}),
                        "at": created_at,
                    },
                )
            await session.commit()
        return task


class MemoryWorld:
    def __init__(self) -> None:
        self.agents = InMemoryStandingAgentStore()
        self.coding = CodingTaskService(InMemoryCodingTaskRepository(), InMemoryCodingEventStore())
        self.source = InMemoryAgentSpendSource()

    async def task(self, *, owner, agent_id, mode, created_at, costs):
        task = await self.coding.create_task(
            owner_id=owner, prompt="p", mode=CodingTaskMode(mode), agent_id=agent_id
        )
        if agent_id is not None:
            self.source.record(
                task.task_id,
                agent_id=agent_id,
                mode=mode,
                created_at=created_at,
                cost_micros=costs[-1] if costs else 0,
            )
        return task


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


@pytest.mark.asyncio
async def test_spend_is_the_latest_checkpoint_of_each_task_this_month(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")
    other = await world.agents.create(BOB, "Dot")
    mid = OCT + timedelta(days=3)
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background", created_at=mid,
                     costs=[10, 30, 70])
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="autonomous", created_at=mid,
                     costs=[5, 200])
    # Not this agent's, not an agent's, not this month's, or not started yet:
    await world.task(owner=BOB, agent_id=other.agent_id, mode="background", created_at=mid,
                     costs=[999])
    await world.task(owner=ALICE, agent_id=None, mode="interactive", created_at=mid, costs=[999])
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background",
                     created_at=OCT - timedelta(seconds=1), costs=[999])
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background", created_at=mid,
                     costs=[])

    spend = await world.source.spent(agent.agent_id, *month_bounds(mid))

    assert spend == AgentSpend(total_micros=270, background_micros=70)


@pytest.mark.asyncio
async def test_an_agent_with_no_tasks_has_spent_nothing(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")

    assert await world.source.spent(agent.agent_id, *month_bounds(OCT)) == AgentSpend()


@pytest.mark.asyncio
async def test_the_end_of_the_month_is_exclusive(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")
    start, end = month_bounds(OCT)
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background", created_at=end,
                     costs=[40])
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background", created_at=start,
                     costs=[3])

    assert (await world.source.spent(agent.agent_id, start, end)).total_micros == 3


@pytest.mark.asyncio
async def test_archived_tasks_still_count() -> None:
    """Archiving hides a task; it does not refund what it spent."""
    await _seed_users()
    world = PostgresWorld()
    agent = await world.agents.create(ALICE, "Dot")
    task = await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background",
                            created_at=OCT, costs=[12])
    async with await db_manager.get_session() as session:
        await session.execute(
            text("UPDATE coding_tasks SET status = 'archived' WHERE task_id = :t"),
            {"t": task.task_id},
        )
        await session.commit()

    assert (await world.source.spent(agent.agent_id, *month_bounds(OCT))).total_micros == 12


# -- the gate: an agent over its envelope opens nothing --------------------------


def _envelope(source, *, limit=100, share=0.5, reserve=False, now=OCT + timedelta(days=2)):
    return AgentBudgetEnvelope(
        source, limit_micros=limit, background_share=share,
        reserve_background_share=reserve, clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_an_agent_over_its_envelope_opens_nothing(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="autonomous",
                     created_at=OCT + timedelta(days=1), costs=[100])

    for mode in (CodingTaskMode.BACKGROUND, CodingTaskMode.AUTONOMOUS):
        with pytest.raises(AgentTaskRefused) as raised:
            await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                                  mode=mode, envelope=_envelope(world.source))
        assert raised.value.reason == OVER_ENVELOPE


@pytest.mark.asyncio
async def test_a_spent_background_share_still_lets_handed_over_work_open(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background",
                     created_at=OCT + timedelta(days=1), costs=[50])
    envelope = _envelope(world.source)

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                              envelope=envelope)
    task = await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                                 mode=CodingTaskMode.AUTONOMOUS, envelope=envelope)

    assert raised.value.reason == OVER_BACKGROUND_SHARE
    assert task.mode is CodingTaskMode.AUTONOMOUS


@pytest.mark.asyncio
async def test_last_months_spend_does_not_close_this_month(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background",
                     created_at=OCT - timedelta(days=3), costs=[10_000])

    task = await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                                 envelope=_envelope(world.source))

    assert task.agent_id == agent.agent_id


@pytest.mark.asyncio
async def test_no_envelope_is_no_gate() -> None:
    world = MemoryWorld()
    agent = await world.agents.create(ALICE, "Dot")
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="background", created_at=OCT,
                     costs=[10**12])

    task = await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p")

    assert task.agent_id == agent.agent_id


@pytest.mark.asyncio
async def test_a_paused_agent_is_refused_before_the_envelope_is_read() -> None:
    """The cheap refusal first: a paused agent never costs a spend query."""

    class Exploding:
        async def spent(self, *_args):
            raise AssertionError("read the envelope")

    world = MemoryWorld()
    agent = await world.agents.create(ALICE, "Dot")
    from neos.standing.models import StandingAgentStatus

    await world.agents.update(ALICE, agent.agent_id, status=StandingAgentStatus.PAUSED)

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                              envelope=_envelope(Exploding()))
    assert raised.value.reason == "agent_paused"


@pytest.mark.asyncio
async def test_the_self_introduction_is_inside_the_envelope() -> None:
    """A zero envelope refuses even the first task -- no path opens around it."""
    world = MemoryWorld()
    agent = await world.agents.create(ALICE, "Dot")

    with pytest.raises(AgentTaskRefused) as raised:
        await start_onboarding(world.agents, world.coding, agent, channels=[], skills=[],
                               envelope=_envelope(world.source, limit=0))

    assert raised.value.reason == OVER_ENVELOPE
    assert (await world.agents.get_owned(ALICE, agent.agent_id)).onboarding_task_id is None


@pytest.mark.asyncio
async def test_a_reserved_share_keeps_background_work_open_after_handed_over_work(world) -> None:
    agent = await world.agents.create(ALICE, "Dot")
    await world.task(owner=ALICE, agent_id=agent.agent_id, mode="autonomous",
                     created_at=OCT + timedelta(days=1), costs=[50])
    envelope = _envelope(world.source, reserve=True)

    with pytest.raises(AgentTaskRefused) as raised:
        await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                              mode=CodingTaskMode.AUTONOMOUS, envelope=envelope)
    task = await open_agent_task(world.agents, world.coding, owner_id=ALICE, prompt="p",
                                 envelope=envelope)

    assert raised.value.reason == OVER_HANDED_OVER_SHARE
    assert task.mode is CodingTaskMode.BACKGROUND


def test_the_share_is_reserved_unless_switched_off() -> None:
    """The verdict's own default matches the setting's: reserved."""
    verdict = envelope_verdict(
        AgentSpend(total_micros=50), limit_micros=100, background_share=0.5,
        mode="autonomous", period_start=START,
    )

    assert verdict.reason == OVER_HANDED_OVER_SHARE
    assert verdict.reserve_background_share is True


@pytest.mark.asyncio
async def test_an_envelope_built_by_hand_reserves_too() -> None:
    source = InMemoryAgentSpendSource()
    source.record("t1", agent_id="sa_1", mode="autonomous", created_at=OCT, cost_micros=50)
    envelope = AgentBudgetEnvelope(source, limit_micros=100, background_share=0.5,
                                   clock=lambda: OCT)

    assert (await envelope.judge("sa_1", "autonomous")).reason == OVER_HANDED_OVER_SHARE
