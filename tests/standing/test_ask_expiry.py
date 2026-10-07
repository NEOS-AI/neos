"""Q9d: an unanswered agent question expires (design §8, decision Q-C).

Expiry does NOT end the task: the ask goes `expired`, the task `waiting_user ->
running` on the same run's latest checkpoint, the woken loop gives `ask_user.v1`
an `ask_expired` denial, and the owner gets one `ask_expired` notice -- sent to
the same place the question went. Answered asks never expire; an answer racing the
expiry -> exactly one wins. Users are `test_q9_*` (shared test DB).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from neos.coding.domain.approvals import evaluate_approval
from neos.coding.domain.phases import CodingRunStatus
from neos.database.connection import db_manager
from neos.standing.asks import (
    AgentAsks,
    ReplyDestination,
    expire_due_asks,
    expired_notice,
    question_notice,
)
from tests.standing.test_ask_repository import (
    CALL,
    STATE,
    VALIDATED,
    MemoryWorld,
    PostgresWorld,
    _seed_users,
)

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(hours=24)
AFTER = EXPIRES + timedelta(seconds=1)
TELEGRAM = ReplyDestination("telegram", "42", "v2:telegram:dm:42:-")


@pytest.fixture(params=["memory", "postgres"])
async def world(request):
    if request.param == "memory":
        return MemoryWorld()
    await _seed_users()
    return PostgresWorld()


async def _asked(world):
    task_id, run_id, lease = await world.waiting_task()
    agent_id = await world.agent()
    ask_id = f"spa_exp_{task_id[-8:]}"
    notice, target = question_notice(
        ask_id, agent_id, ["Which branch?"], TELEGRAM, max_body_chars=3500
    )
    commit = await world.runs.request_user_answer(
        lease=lease,
        tool_call=CALL,
        validated=VALIDATED,
        loop_state=STATE,
        workspace_revision="rev",
        agent_id=agent_id,
        reply_session_id=TELEGRAM.session_id,
        reply_channel_type="telegram",
        asked_at=NOW,
        expires_at=EXPIRES,
        ask_id=ask_id,
        notice=notice,
        notice_target=target,
    )
    return task_id, run_id, commit


def _notice_for(ask):
    return expired_notice(ask, max_body_chars=3500)


async def _expire(world, now=AFTER):
    return await world.runs.expire_user_questions(limit=50, now=now, notice_for=_notice_for)


async def _notices(world, agent_id):
    if isinstance(world, MemoryWorld):
        return [(n.kind, n.dedupe_key) for n, _target in world.runs.notices]
    async with await db_manager.get_session() as session:
        rows = await session.execute(
            text(
                "SELECT kind, dedupe_key, channel_type, channel_id FROM standing_notifications "
                "WHERE agent_id = :a ORDER BY created_at, kind"
            ),
            {"a": agent_id},
        )
        return [tuple(row) for row in rows]


@pytest.mark.asyncio
async def test_expiry_resumes_the_task_and_sends_one_notice(world) -> None:
    task_id, run_id, asked = await _asked(world)

    [commit] = await _expire(world)

    assert commit.ask.status == "expired" and commit.ask.ask_id == asked.ask.ask_id
    assert commit.resumed is True
    [status] = commit.events
    assert status.type == "task.status.changed"
    assert status.payload == {"status": "running", "reason_code": "ask_expired"}
    assert status.run_id == run_id
    assert commit.checkpoint_id == asked.checkpoint.checkpoint_id == status.checkpoint_id
    assert await world.task_status(task_id) == "running"
    assert await world.run_status(run_id) == CodingRunStatus.RUNNING.value  # the task does not end
    notices = await _notices(world, await world.agent())
    expired_rows = [n for n in notices if n[0] == "ask_expired"]
    assert [n[1] for n in expired_rows] == [f"ask_expired:{asked.ask.ask_id}"]
    if isinstance(world, PostgresWorld):
        assert expired_rows[0][2:] == ("telegram", "42")  # where the question went
    assert await _expire(world) == []  # once


@pytest.mark.asyncio
async def test_a_question_not_yet_due_is_left_alone(world) -> None:
    task_id, _run_id, _asked_commit = await _asked(world)

    assert await _expire(world, now=EXPIRES - timedelta(seconds=1)) == []
    assert await world.task_status(task_id) == "waiting_user"


@pytest.mark.asyncio
async def test_an_answered_question_never_expires(world) -> None:
    task_id, run_id, asked = await _asked(world)
    if isinstance(world, MemoryWorld):
        world.runs.task_owners[task_id] = "test_q9_repo_owner"
    answered = await world.runs.answer_user_question(
        ask_id=asked.ask.ask_id,
        owner_id="test_q9_repo_owner",
        answers=["main"],
        channel_type="telegram",
        now=NOW + timedelta(hours=1),
    )
    assert answered is not None

    assert await _expire(world) == []
    assert (await world.asks.for_call(task_id, run_id, "a1")).status == "answered"
    assert not [n for n in await _notices(world, await world.agent()) if n[0] == "ask_expired"]


@pytest.mark.asyncio
async def test_an_answer_racing_the_expiry_exactly_one_wins(world) -> None:
    task_id, run_id, asked = await _asked(world)
    if isinstance(world, MemoryWorld):
        world.runs.task_owners[task_id] = "test_q9_repo_owner"

    answered, expired = await asyncio.gather(
        world.runs.answer_user_question(
            ask_id=asked.ask.ask_id,
            owner_id="test_q9_repo_owner",
            answers=["main"],
            channel_type="telegram",
            now=AFTER,
        ),
        _expire(world),
    )

    assert (answered is not None) != bool(expired)
    final = (await world.asks.for_call(task_id, run_id, "a1")).status
    assert final == ("answered" if answered is not None else "expired")
    assert await world.task_status(task_id) == "running"


# ---- the poller step: wake + count ------------------------------------------------


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_the_poller_wakes_each_resumed_task_once_and_counts() -> None:
    from neos.observability.metrics import metrics

    world = MemoryWorld()
    task_id, _run_id, asked = await _asked(world)
    woken = []

    async def wake(task, checkpoint_id):
        woken.append((task, checkpoint_id))

    before = metrics.standing_ask_total.labels(outcome="expired")._value.get()

    commits = await expire_due_asks(
        world.runs, limit=50, now=AFTER, wake=wake, max_body_chars=3500
    )
    again = await expire_due_asks(
        world.runs, limit=50, now=AFTER, wake=wake, max_body_chars=3500
    )

    assert len(commits) == 1 and again == []
    assert woken == [(task_id, asked.checkpoint.checkpoint_id)]
    assert metrics.standing_ask_total.labels(outcome="expired")._value.get() == before + 1


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_a_failed_wake_does_not_undo_the_expiry() -> None:
    world = MemoryWorld()
    task_id, run_id, _asked_commit = await _asked(world)

    async def wake(task, checkpoint_id):
        raise RuntimeError("broker down")

    commits = await expire_due_asks(world.runs, limit=50, now=AFTER, wake=wake, max_body_chars=3500)

    assert len(commits) == 1
    assert world.runs.task_statuses[task_id] == "running"  # the reconciliation sweep finds it


@pytest.mark.no_db
def test_the_expired_notice_names_the_question() -> None:
    from neos.standing.asks import PendingAsk

    ask = PendingAsk(
        ask_id="spa_9", agent_id="sa_1", task_id="ct_1", run_id="cr_1", tool_call_id="a1",
        questions=("Which branch?", "Run tests?"), reply_session_id=None,
        asked_at=NOW, expires_at=EXPIRES, status="expired",
    )

    notice = expired_notice(ask, max_body_chars=3500)

    assert (notice.kind, notice.dedupe_key, notice.agent_id) == (
        "ask_expired", "ask_expired:spa_9", "sa_1",
    )
    assert "Which branch?" in notice.body
    assert "without" in notice.body.lower()


# ---- in the loop: the resumed task gets `ask_expired` -----------------------------


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_after_expiry_the_resumed_loop_denies_with_ask_expired() -> None:
    from tests.coding.loop.test_anthropic_loop import INPUT, completed, harness, tool_call

    h = harness(
        [[tool_call("a1", "ask_user.v1", {"questions": ["Which branch?"]}), completed()], [completed()]],
        approval_evaluator=evaluate_approval,
    )

    async def destination(agent_id, owner_id):
        return TELEGRAM

    h.loop._asks = AgentAsks(store=h.repository.asks, destination=destination, expire_hours=3)
    task = replace(INPUT, mode="autonomous", agent_id="sa_q9", owner_id="u_q9")
    [event async for event in h.loop.run(task, None, h.deps)]

    asked_at = h.repository.asks.rows[next(iter(h.repository.asks.rows))].asked_at
    early = await h.repository.expire_user_questions(
        limit=10, now=asked_at + timedelta(hours=3) - timedelta(seconds=1), notice_for=_notice_for
    )
    on_time = await h.repository.expire_user_questions(
        limit=10, now=asked_at + timedelta(hours=3), notice_for=_notice_for
    )
    assert early == [] and len(on_time) == 1  # `expire_hours` from the port

    events = [event async for event in h.loop.run(task, h.repository.checkpoints[-1], h.deps)]

    denied = [e.payload.get("reason_code") for e in events if e.type == "tool.denied"]
    assert denied == ["ask_expired"]
    assert h.executor.calls == []


# ---- beat registration ------------------------------------------------------------


@pytest.mark.no_db
def test_beat_has_the_expiry_poller_only_when_the_flag_is_on() -> None:
    from neos.workflow.celery_app import app, configure_standing_ask_beat_schedule

    assert "expire-standing-asks" not in app.conf.beat_schedule  # default: flag off

    schedule: dict = {}
    configure_standing_ask_beat_schedule(schedule, enabled=True)
    assert schedule["expire-standing-asks"]["task"] == "neos.tasks.expire_standing_asks"
    assert schedule["expire-standing-asks"]["schedule"] == 60.0
    configure_standing_ask_beat_schedule(schedule, enabled=False)
    assert schedule == {}


@pytest.mark.no_db
def test_the_expiry_task_is_registered_under_its_beat_name() -> None:
    import neos.tasks as tasks

    assert tasks.expire_standing_asks.name == "neos.tasks.expire_standing_asks"


@pytest.mark.asyncio
async def test_an_answer_holding_the_row_wins_over_a_concurrent_expiry() -> None:
    """The race made deterministic on the real DB: an answer transaction holds the ask
    row (locked, not yet committed) while the poller runs. The poller must skip the row
    (`SKIP LOCKED`) -- not wait and then overwrite the answer with `expired`."""
    await _seed_users()
    world = PostgresWorld()
    task_id, run_id, asked = await _asked(world)

    async with await db_manager.get_session() as answering:
        await answering.begin()
        await answering.execute(
            text("SELECT ask_id FROM standing_pending_asks WHERE ask_id = :a FOR UPDATE"),
            {"a": asked.ask.ask_id},
        )
        expiry = asyncio.create_task(_expire(world))
        await asyncio.sleep(0.3)  # the poller reaches the locked row while the answer is open
        await answering.execute(
            text(
                "UPDATE standing_pending_asks SET status = 'answered', answered_at = :now, "
                "answers = '[\"main\"]'::jsonb WHERE ask_id = :a"
            ),
            {"a": asked.ask.ask_id, "now": AFTER},
        )
        await answering.commit()
    expired = await asyncio.wait_for(expiry, timeout=10)

    assert expired == []
    assert (await world.asks.for_call(task_id, run_id, "a1")).status == "answered"


@pytest.mark.asyncio
async def test_a_skipped_expired_notice_is_logged(caplog) -> None:
    """Final review (Q9-4): no question notice to stand beside -> no `ask_expired`
    notice, and a warning says so. Mutation: drop the warning."""
    await _seed_users()
    world = PostgresWorld()
    task_id, run_id, lease = await world.waiting_task()
    commit = await world.runs.request_user_answer(  # asked without its notice
        lease=lease,
        tool_call=CALL,
        validated=VALIDATED,
        loop_state=STATE,
        workspace_revision="rev",
        agent_id=await world.agent(),
        reply_session_id=TELEGRAM.session_id,
        reply_channel_type="telegram",
        asked_at=NOW,
        expires_at=EXPIRES,
    )
    caplog.set_level("WARNING", logger="neos.coding.repositories.run_repository")

    commits = await _expire(world)

    assert commit.ask.ask_id in {c.ask.ask_id for c in commits}
    assert [n for n in await _notices(world, await world.agent()) if n[0] == "ask_expired"] == []
    assert any(
        commit.ask.ask_id in r.getMessage() and "notice" in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    )
