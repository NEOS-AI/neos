"""Q3: the standing-question store (one contract, two stores), the DA reader on a
real ledger, and the poll that settles and dispatches (design §5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.database.connection import db_manager
from neos.database.deep_analysis_models import DABlob, DAClaim, DAEvidence, DAQuestion, DARun
from neos.standing.budget import OVER_BACKGROUND_SHARE, AgentBudgetEnvelope, InMemoryAgentSpendSource
from neos.standing.notifications import (
    KIND_QUESTION_CHANGED,
    InMemoryNotificationStore,
    NotifyTarget,
    StandingNotifier,
)
from neos.standing.questions import (
    SKIP_AGENT_NOT_ACTIVE,
    ClaimRecord,
    InMemoryQuestionStore,
    PostgresDAReader,
    PostgresQuestionStore,
    QuestionRefused,
    poll_once,
)
from neos.standing.store import PostgresStandingAgentStore
from neos.workflow.deep_analysis.text_norm import claim_hash

ALICE = "test_q3_question_alice"
BOB = "test_q3_question_bob"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=7)


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


async def _da_run(owner=ALICE, status="completed", claims=()) -> str:
    """A real DA ledger: run, one question, claims, their blobs and evidence."""
    run_id = uuid4().hex[:8]
    async with await db_manager.get_session() as session:
        session.add(DARun(id=run_id, root_question="q", profile="dev", status=status,
                          user_id=owner))
        await session.flush()
        session.add(DAQuestion(id="q1", run_id=run_id, parent_id=None, text="q", depth=0,
                               value_est=1.0, cap_tokens=1000))
        await session.flush()
        for text_, claim_status, blobs in claims:
            claim_id = uuid4().hex[:8]
            session.add(DAClaim(id=claim_id, run_id=run_id, question_id="q1", text=text_,
                                hash=claim_hash(text_), status=claim_status, confidence=0.9))
            await session.flush()
            for blob in blobs:
                existing = await session.get(DABlob, (run_id, blob))
                if existing is None:
                    session.add(DABlob(run_id=run_id, content_hash=blob, url=f"https://x/{blob}",
                                       http_status=200, raw_text=blob))
                    await session.flush()
                session.add(DAEvidence(id=uuid4().hex[:8], run_id=run_id, claim_id=claim_id,
                                       source_url=f"https://x/{blob}", excerpt="e", raw_ref=blob))
        await session.commit()
    return run_id


class MemoryWorld:
    def __init__(self) -> None:
        self.store = InMemoryQuestionStore()

    async def agent(self, owner, *, active=True):
        agent_id = f"sa_{uuid4().hex}"
        self.store.agents[agent_id] = (owner, active)
        return agent_id

    async def da_run(self, **kwargs):
        return uuid4().hex[:8]


class PostgresWorld:
    def __init__(self) -> None:
        self.store = PostgresQuestionStore(db_manager.get_session)
        self.agents = PostgresStandingAgentStore(db_manager.get_session)

    async def agent(self, owner, *, active=True):
        async with await db_manager.get_session() as session:
            await session.execute(
                text("DELETE FROM standing_agents WHERE owner_id = :o"), {"o": owner}
            )
            await session.commit()
        agent = await self.agents.create(owner, "Dot")
        if not active:
            async with await db_manager.get_session() as session:
                await session.execute(
                    text("UPDATE standing_agents SET status = 'paused' WHERE agent_id = :a"),
                    {"a": agent.agent_id},
                )
                await session.commit()
        return agent.agent_id

    async def da_run(self, **kwargs):
        return await _da_run(**kwargs)


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


async def _create(world, owner, agent_id, *, max_per_agent=5, next_run_at=NOW):
    return await world.store.create(
        owner, agent_id, question="What changed in rates?", cron_expression="0 */6 * * *",
        next_run_at=next_run_at, max_per_agent=max_per_agent, now=NOW,
    )


# -- the store -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_questions_belong_to_the_agents_owner(world) -> None:
    agent_id = await world.agent(ALICE)

    assert await _create(world, BOB, agent_id) is None
    question = await _create(world, ALICE, agent_id)

    assert question.question_id.startswith("sq_")
    assert await world.store.get(ALICE, question.question_id) == question
    assert await world.store.get(BOB, question.question_id) is None
    assert [q.question_id for q in await world.store.list_for_agent(ALICE, agent_id)] == [
        question.question_id
    ]
    assert await world.store.list_for_agent(BOB, agent_id) == []
    assert await world.store.set_enabled(BOB, question.question_id, False, now=NOW) is None
    assert await world.store.delete(BOB, question.question_id, now=NOW) is False
    assert (await world.store.set_enabled(ALICE, question.question_id, False, now=NOW)).enabled is False
    assert await world.store.delete(ALICE, question.question_id, now=NOW) is True
    assert await world.store.get(ALICE, question.question_id) is None


@pytest.mark.asyncio
async def test_an_agent_holds_at_most_max_per_agent_live_questions(world) -> None:
    agent_id = await world.agent(ALICE)
    first = await _create(world, ALICE, agent_id, max_per_agent=2)
    await _create(world, ALICE, agent_id, max_per_agent=2)

    with pytest.raises(QuestionRefused) as refused:
        await _create(world, ALICE, agent_id, max_per_agent=2)
    assert refused.value.reason == "too_many_questions"

    await world.store.delete(ALICE, first.question_id, now=NOW)
    assert await _create(world, ALICE, agent_id, max_per_agent=2) is not None


@pytest.mark.asyncio
async def test_due_means_enabled_live_on_time_and_not_in_flight(world) -> None:
    agent_id = await world.agent(ALICE)
    due = await _create(world, ALICE, agent_id)
    later = await _create(world, ALICE, agent_id, next_run_at=NOW + timedelta(hours=1))
    off = await _create(world, ALICE, agent_id)
    gone = await _create(world, ALICE, agent_id)
    busy = await _create(world, ALICE, agent_id)
    await world.store.set_enabled(ALICE, off.question_id, False, now=NOW)
    await world.store.delete(ALICE, gone.question_id, now=NOW)
    await world.store.record_dispatch(
        busy.question_id, await world.da_run(status="running"), next_run_at=NOW, now=NOW
    )

    claimed = await world.store.claim_due(now=NOW, limit=50)

    ids = {item.question.question_id for item in claimed}
    assert due.question_id in ids
    assert ids.isdisjoint({later.question_id, off.question_id, gone.question_id, busy.question_id})
    [mine] = [item for item in claimed if item.question.question_id == due.question_id]
    assert (mine.owner_id, mine.agent_active) == (ALICE, True)


@pytest.mark.asyncio
async def test_one_run_in_flight_per_question_and_the_baseline_is_the_last_settled(world) -> None:
    agent_id = await world.agent(ALICE)
    question = await _create(world, ALICE, agent_id)
    first, second, third = [await world.da_run() for _ in range(3)]

    assert await world.store.baseline_run(question.question_id) is None
    await world.store.record_dispatch(question.question_id, first, next_run_at=LATER, now=NOW)
    await world.store.settle(question.question_id, first, status="settled",
                             diff={"baseline": True}, notified=False, now=NOW)
    await world.store.record_dispatch(question.question_id, second, next_run_at=LATER,
                                      now=NOW + timedelta(hours=6))
    await world.store.settle(question.question_id, second, status="failed",
                             diff={"reason": "failed"}, notified=False, now=NOW)
    await world.store.record_dispatch(question.question_id, third, next_run_at=LATER,
                                      now=NOW + timedelta(hours=12))

    assert await world.store.baseline_run(question.question_id) == first  # failed is not a baseline
    assert [r.da_run_id for r in await world.store.in_flight()
            if r.question_id == question.question_id] == [third]
    runs = await world.store.runs(ALICE, question.question_id, limit=10)
    assert [(r.da_run_id, r.status) for r in runs] == [
        (third, "dispatched"), (second, "failed"), (first, "settled")
    ]
    assert await world.store.runs(BOB, question.question_id, limit=10) == []


@pytest.mark.asyncio
async def test_a_second_run_cannot_be_in_flight() -> None:
    await _seed_users()
    world = PostgresWorld()
    agent_id = await world.agent(ALICE)
    question = await _create(world, ALICE, agent_id)
    await world.store.record_dispatch(question.question_id, await world.da_run(),
                                      next_run_at=LATER, now=NOW)

    with pytest.raises(Exception, match="uq_standing_question_runs_one_in_flight"):
        await world.store.record_dispatch(question.question_id, await world.da_run(),
                                          next_run_at=LATER, now=NOW)


@pytest.mark.asyncio
async def test_a_claimed_question_is_held_from_a_second_poller() -> None:
    await _seed_users()
    world = PostgresWorld()
    agent_id = await world.agent(ALICE)
    question = await _create(world, ALICE, agent_id)

    first = await world.store.claim_due(now=NOW, limit=50)
    second = await world.store.claim_due(now=NOW, limit=50)

    assert question.question_id in {item.question.question_id for item in first}
    assert question.question_id not in {item.question.question_id for item in second}


@pytest.mark.asyncio
async def test_deleting_the_owner_is_not_blocked_by_questions() -> None:
    await _seed_users()
    world = PostgresWorld()
    agent_id = await world.agent(BOB)
    question = await _create(world, BOB, agent_id)
    await world.store.record_dispatch(question.question_id, await _da_run(owner=BOB),
                                      next_run_at=LATER, now=NOW)

    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": BOB})
        await session.commit()
        left = (
            await session.execute(
                text("SELECT count(*) FROM standing_questions WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()
    assert left == 0


# -- the DA reader on a real ledger -------------------------------------------


@pytest.mark.asyncio
async def test_the_reader_returns_each_claim_with_its_evidence_blobs() -> None:
    await _seed_users()
    run_id = await _da_run(claims=[
        ("Rates rose in May.", "verified", ["b1", "b2"]),
        ("Inflation fell.", "rejected", ["b2"]),
        ("No evidence yet.", "pending", []),
    ])
    reader = PostgresDAReader(db_manager.get_session)

    claims = {c.text: c for c in await reader.claims(run_id)}

    assert await reader.status(run_id) == "completed"
    assert await reader.status("nope0000") is None
    assert claims["Rates rose in May."] == ClaimRecord(
        claim_hash("Rates rose in May."), "Rates rose in May.", "verified", frozenset({"b1", "b2"})
    )
    assert claims["Inflation fell."].evidence == frozenset({"b2"})
    assert claims["No evidence yet."].evidence == frozenset()


# -- the poll --------------------------------------------------------------------


class Reader:
    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}
        self.ledgers: dict[str, list[ClaimRecord]] = {}

    async def status(self, da_run_id):
        return self.statuses.get(da_run_id)

    async def claims(self, da_run_id):
        return self.ledgers.get(da_run_id, [])


def _claim(text_, status="verified", evidence=()):
    return ClaimRecord(claim_hash(text_), text_, status, frozenset(evidence))


class Poll:
    """A memory store, a scripted DA, a notifier with a target."""

    def __init__(self, *, active=True, envelope=None, submit_fails=False) -> None:
        self.store = InMemoryQuestionStore({"sa_1": (ALICE, active)})
        self.reader = Reader()
        notices = InMemoryNotificationStore({"sa_1": ALICE})
        notices.targets["sa_1"] = NotifyTarget("slack", "C1")
        self.notices = notices
        self.notifier = StandingNotifier(notices, max_body_chars=3_500, clock=lambda: NOW)
        self.envelope = envelope
        self.submitted: list[tuple[str, str, str]] = []
        self.submit_fails = submit_fails

    async def submit(self, owner_id, question, profile):
        if self.submit_fails:
            raise RuntimeError("broker down")
        run_id = f"da{len(self.submitted):06d}"
        self.submitted.append((owner_id, question, profile))
        self.reader.statuses[run_id] = "running"
        return run_id

    async def question(self):
        return await self.store.create(
            ALICE, "sa_1", question="What changed in rates?", cron_expression="0 */6 * * *",
            next_run_at=NOW, max_per_agent=5, now=NOW,
        )

    async def poll(self, now):
        return await poll_once(
            self.store, self.reader, submit=self.submit, envelope=self.envelope,
            notifier=self.notifier, profile="default", max_claims=5,
            settle_timeout=timedelta(hours=12), now=now,
        )

    def finish(self, run_id, claims, status="completed"):
        self.reader.statuses[run_id] = status
        self.reader.ledgers[run_id] = claims

    def notices_sent(self):
        return [row for row in self.notices.rows.values() if row["kind"] == KIND_QUESTION_CHANGED]


@pytest.mark.asyncio
async def test_the_first_run_is_a_baseline_and_says_nothing() -> None:
    poll = Poll()
    question = await poll.question()

    first = await poll.poll(NOW)
    [run_id] = first.dispatched
    assert poll.submitted == [(ALICE, "What changed in rates?", "default")]
    poll.finish(run_id, [_claim("Rates rose in May.")])
    second = await poll.poll(NOW + timedelta(minutes=1))

    assert second.settled == [run_id] and second.notified == []
    [run] = await poll.store.runs(ALICE, question.question_id, limit=5)
    assert run.diff == {"baseline": True}
    assert poll.notices_sent() == []


@pytest.mark.asyncio
async def test_a_change_is_told_once_with_the_new_and_the_refuted() -> None:
    poll = Poll()
    question = await poll.question()
    [first] = (await poll.poll(NOW)).dispatched
    poll.finish(first, [_claim("Rates rose in May."), _claim("Inflation fell.")])
    await poll.poll(NOW + timedelta(minutes=1))

    [second] = (await poll.poll(NOW + timedelta(hours=6))).dispatched
    poll.finish(second, [_claim("Rates rose in May.", "rejected"), _claim("Inflation fell."),
                         _claim("The bank paused in June.")])
    report = await poll.poll(NOW + timedelta(hours=6, minutes=1))

    assert report.notified == [second]
    [notice] = poll.notices_sent()
    assert notice["dedupe_key"] == f"question:{question.question_id}:{second}"
    assert "새로 검증 1:" in notice["body"] and "The bank paused in June." in notice["body"]
    assert "반증 1:" in notice["body"] and "Rates rose in May." in notice["body"]
    [latest, *_] = await poll.store.runs(ALICE, question.question_id, limit=5)
    assert latest.notified is True
    assert latest.diff["baseline_run_id"] == first
    assert latest.diff["newly_verified"] == [claim_hash("The bank paused in June.")]


@pytest.mark.asyncio
async def test_no_change_no_notice_and_the_diff_is_against_the_last_settled_run() -> None:
    poll = Poll()
    await poll.question()
    claims = [_claim("Rates rose in May.")]
    [first] = (await poll.poll(NOW)).dispatched
    poll.finish(first, claims)
    await poll.poll(NOW + timedelta(minutes=1))
    [second] = (await poll.poll(NOW + timedelta(hours=6))).dispatched
    poll.finish(second, [], status="failed")
    await poll.poll(NOW + timedelta(hours=6, minutes=1))
    [third] = (await poll.poll(NOW + timedelta(hours=12))).dispatched
    poll.finish(third, claims)

    report = await poll.poll(NOW + timedelta(hours=12, minutes=1))

    assert report.settled == [third] and report.notified == []
    assert poll.notices_sent() == []


@pytest.mark.asyncio
async def test_a_failed_run_is_settled_as_failed_and_does_not_block_the_next() -> None:
    poll = Poll()
    question = await poll.question()
    [first] = (await poll.poll(NOW)).dispatched
    poll.finish(first, [], status="failed")

    report = await poll.poll(NOW + timedelta(minutes=1))

    assert report.failed == [first]
    assert await poll.store.baseline_run(question.question_id) is None


@pytest.mark.asyncio
async def test_a_run_that_never_finishes_times_out() -> None:
    poll = Poll()
    question = await poll.question()
    [first] = (await poll.poll(NOW)).dispatched

    assert (await poll.poll(NOW + timedelta(hours=11))).failed == []
    report = await poll.poll(NOW + timedelta(hours=12, minutes=1))

    assert report.failed == [first]
    runs = {r.da_run_id: r for r in await poll.store.runs(ALICE, question.question_id, limit=5)}
    assert runs[first].diff == {"reason": "timeout"}
    assert report.dispatched  # the next one goes out in the same poll
    assert runs[report.dispatched[0]].status == "dispatched"


@pytest.mark.asyncio
async def test_a_paused_agent_asks_nothing() -> None:
    poll = Poll(active=False)
    question = await poll.question()

    report = await poll.poll(NOW)

    assert poll.submitted == []
    assert report.skipped == {question.question_id: SKIP_AGENT_NOT_ACTIVE}
    stored = await poll.store.get(ALICE, question.question_id)
    assert stored.last_skip_reason == SKIP_AGENT_NOT_ACTIVE
    assert stored.next_run_at > NOW


@pytest.mark.asyncio
async def test_an_agent_out_of_background_budget_asks_nothing() -> None:
    source = InMemoryAgentSpendSource()
    source.record("ct_0", agent_id="sa_1", mode="background", created_at=NOW, cost_micros=50)
    envelope = AgentBudgetEnvelope(source, limit_micros=100, background_share=0.5,
                                   clock=lambda: NOW)
    poll = Poll(envelope=envelope)
    question = await poll.question()

    report = await poll.poll(NOW)

    assert poll.submitted == []
    assert report.skipped == {question.question_id: OVER_BACKGROUND_SHARE}


@pytest.mark.asyncio
async def test_a_skip_clears_on_the_next_dispatch() -> None:
    poll = Poll(submit_fails=True)
    question = await poll.question()
    await poll.poll(NOW)
    assert (await poll.store.get(ALICE, question.question_id)).last_skip_reason == "dispatch_failed"

    poll.submit_fails = False
    report = await poll.poll(NOW + timedelta(hours=6))

    assert report.dispatched
    assert (await poll.store.get(ALICE, question.question_id)).last_skip_reason is None


@pytest.mark.asyncio
async def test_a_deleted_questions_run_is_settled_but_not_told() -> None:
    poll = Poll()
    question = await poll.question()
    [first] = (await poll.poll(NOW)).dispatched
    poll.finish(first, [_claim("A.")])
    await poll.poll(NOW + timedelta(minutes=1))
    [second] = (await poll.poll(NOW + timedelta(hours=6))).dispatched
    await poll.store.delete(ALICE, question.question_id, now=NOW)
    poll.finish(second, [_claim("A."), _claim("B.")])

    report = await poll.poll(NOW + timedelta(hours=6, minutes=1))

    assert report.settled == [second] and report.notified == []
    assert poll.notices_sent() == []
