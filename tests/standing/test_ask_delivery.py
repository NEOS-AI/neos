"""Q9b: an agent's question goes out through the notice queue (design §6).

Where to ask (§6.1): the attached channel session the owner spoke in last -> the
agent's notify target -> nowhere (`no_reply_channel`). What to send (§6.2): the
questions, their options, "Reply in this chat to answer.", dedupe `question:{ask_id}`.
The notice row is written in the ask's own transaction; the worker never calls the
gateway. Users are `test_q9_*` (the test DB is shared with another track).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.api.channels.session_key import build_session_key, session_key_destination
from neos.coding.domain.models import CodingTaskMode
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.model.base import ToolCallCompleted
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.tools.registry import CodingToolRegistry
from neos.config.schema import ChannelConfig
from neos.database.connection import db_manager
from neos.standing.asks import (
    PendingAsk,
    ReplyDestination,
    enqueue_question,
    question_notice,
    resolve_reply_destination,
)
from neos.standing.notifications import (
    InMemoryNotificationStore,
    NotifyTarget,
    PostgresNotificationStore,
    StandingNotice,
)
from neos.standing.store import InMemoryStandingAgentStore, PostgresStandingAgentStore
from neos.standing.threads import (
    InMemoryAgentThreadStore,
    PostgresAgentThreadStore,
    reply_session_for,
)

OWNER = "test_q9_delivery_owner"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SLACK = "v2:slack:T1:D1:-"
TELEGRAM = "v2:telegram:dm:42:-"
WEB = "web:conv_1"
PRINCIPALS = ChannelConfig.model_validate(
    {
        "principals": [
            {"platform": "slack", "platform_user_id": "U_owner", "user_id": OWNER},
            {"platform": "telegram", "platform_user_id": "42", "user_id": OWNER},
        ]
    }
)


async def _seed_owner() -> None:
    async with await db_manager.get_session() as session:
        await session.execute(
            text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
            {"u": OWNER, "e": f"{OWNER}@example.com"},
        )
        await session.commit()


@pytest.fixture(params=["memory", "postgres"])
async def stores(request):
    if request.param == "memory":
        agents = InMemoryStandingAgentStore()
        return agents, InMemoryAgentThreadStore(agents)
    await _seed_owner()
    return PostgresStandingAgentStore(db_manager.get_session), PostgresAgentThreadStore(
        db_manager.get_session
    )


async def _speak(threads, agent_id, session_id, channel_type, role="user", content="hi"):
    thread = await threads.attach_session(agent_id, session_id, channel_type)
    await threads.append_turn(thread.agent_thread_id, session_id, channel_type, role, content)


# ---- reply_session_for (§6.1) --------------------------------------------------


@pytest.mark.asyncio
async def test_the_session_the_owner_spoke_in_last_is_chosen(stores) -> None:
    agents, threads = stores
    agent = await agents.create(OWNER, "Dot")
    await _speak(threads, agent.agent_id, SLACK, "slack")
    await _speak(threads, agent.agent_id, TELEGRAM, "telegram")

    chosen = await reply_session_for(threads, agent.agent_id)

    assert (chosen.session_id, chosen.channel_type) == (TELEGRAM, "telegram")


@pytest.mark.asyncio
async def test_only_user_turns_count_and_web_is_never_chosen(stores) -> None:
    agents, threads = stores
    agent = await agents.create(OWNER, "Dot")
    await _speak(threads, agent.agent_id, SLACK, "slack")
    await _speak(threads, agent.agent_id, TELEGRAM, "telegram", role="assistant")
    await _speak(threads, agent.agent_id, WEB, "web")

    chosen = await reply_session_for(threads, agent.agent_id)

    assert chosen.session_id == SLACK


@pytest.mark.asyncio
async def test_after_a_rotation_old_turns_still_choose_the_moved_session(stores) -> None:
    """Rotation moves sessions to the new thread but leaves turns in the archived one."""
    agents, threads = stores
    agent = await agents.create(OWNER, "Dot")
    await _speak(threads, agent.agent_id, SLACK, "slack")
    await threads.rotate(agent.agent_id)

    chosen = await reply_session_for(threads, agent.agent_id)

    assert chosen is not None and chosen.session_id == SLACK
    assert chosen.agent_thread_id == (await threads.active(agent.agent_id)).agent_thread_id


@pytest.mark.asyncio
async def test_a_detached_session_is_not_chosen(stores) -> None:
    agents, threads = stores
    agent = await agents.create(OWNER, "Dot")
    await _speak(threads, agent.agent_id, SLACK, "slack")
    await _speak(threads, agent.agent_id, TELEGRAM, "telegram")
    await threads.detach_session(agent.agent_id, TELEGRAM)

    chosen = await reply_session_for(threads, agent.agent_id)

    assert chosen.session_id == SLACK


@pytest.mark.asyncio
async def test_no_turns_no_session(stores) -> None:
    agents, threads = stores
    agent = await agents.create(OWNER, "Dot")
    await threads.attach_session(agent.agent_id, SLACK, "slack")

    assert await reply_session_for(threads, agent.agent_id) is None


# ---- the address inside a v2 key (decision Q-E) ----------------------------------


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (build_session_key("slack", "T1", "D1", None), ("slack", "D1")),
        (build_session_key("slack", "T1", "D1", "1700.1"), ("slack", "D1")),  # DM top level
        (build_session_key("telegram", "dm", "42", None), ("telegram", "42")),
        (build_session_key("discord", "dm", "99", None), ("discord", "99")),
        ("web:conv_1", None),
        ("v2:slack:T1", None),
        ("", None),
    ],
)
def test_session_key_destination(key, expected) -> None:
    assert session_key_destination(key) == expected


# ---- the destination: session -> notify target -> none --------------------------


class _Threads:
    def __init__(self, session):
        self.session = session

    async def reply_session(self, agent_id):
        return self.session


def _notices(target=None):
    store = InMemoryNotificationStore({"sa_1": OWNER})
    if target is not None:
        store.targets["sa_1"] = target
    return store


def _session(session_id, channel_type):
    return SimpleNamespace(session_id=session_id, channel_type=channel_type)


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_the_destination_is_the_last_session_first() -> None:
    destination = await resolve_reply_destination(
        "sa_1",
        OWNER,
        threads=_Threads(_session(TELEGRAM, "telegram")),
        notices=_notices(NotifyTarget("slack", "C_target")),
        channels=PRINCIPALS,
    )

    assert destination == ReplyDestination("telegram", "42", TELEGRAM)


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_without_a_session_the_notify_target_is_used() -> None:
    destination = await resolve_reply_destination(
        "sa_1",
        OWNER,
        threads=_Threads(None),
        notices=_notices(NotifyTarget("slack", "D_owner")),
        channels=PRINCIPALS,
    )

    assert destination == ReplyDestination("slack", "D_owner", None)


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_neither_session_nor_target_is_none() -> None:
    destination = await resolve_reply_destination(
        "sa_1", OWNER, threads=_Threads(None), notices=_notices(), channels=PRINCIPALS
    )

    assert destination is None


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_a_platform_the_owner_is_not_mapped_on_is_no_destination() -> None:
    """Deviation 5: an answer from there could not be recognised -- never ask there."""
    discord_only_target = await resolve_reply_destination(
        "sa_1",
        OWNER,
        threads=_Threads(_session("v2:discord:dm:99:-", "discord")),
        notices=_notices(NotifyTarget("discord", "99")),
        channels=PRINCIPALS,
    )
    falls_back = await resolve_reply_destination(
        "sa_1",
        OWNER,
        threads=_Threads(_session("v2:discord:dm:99:-", "discord")),
        notices=_notices(NotifyTarget("slack", "D_owner")),
        channels=PRINCIPALS,
    )
    unmapped = await resolve_reply_destination(
        "sa_1",
        OWNER,
        threads=_Threads(_session(SLACK, "slack")),
        notices=_notices(),
        channels=ChannelConfig(),
    )

    assert discord_only_target is None
    assert falls_back == ReplyDestination("slack", "D_owner", None)
    assert unmapped is None


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_a_failing_lookup_is_no_destination() -> None:
    class Broken:
        async def reply_session(self, agent_id):
            raise RuntimeError("db down")

    assert (
        await resolve_reply_destination(
            "sa_1", OWNER, threads=Broken(), notices=_notices(), channels=PRINCIPALS
        )
        is None
    )


# ---- the notice (§6.2) -----------------------------------------------------------


def _ask(questions, *, reply_session_id=SLACK, ask_id="spa_1"):
    return PendingAsk(
        ask_id=ask_id,
        agent_id="sa_1",
        task_id="ct_1",
        run_id="cr_1",
        tool_call_id="a1",
        questions=tuple(questions),
        reply_session_id=reply_session_id,
        asked_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )


@pytest.mark.no_db
def test_one_question_notice() -> None:
    notice, target = question_notice(
        "spa_1", "sa_1", ["Which branch?"], ReplyDestination("slack", "D1", SLACK), max_body_chars=3500
    )

    assert notice.kind == "question_asked"
    assert notice.dedupe_key == "question:spa_1"
    assert notice.agent_id == "sa_1"
    assert "Which branch?" in notice.body
    assert notice.body.rstrip().endswith("Reply in this chat to answer.")
    assert "one line per question" not in notice.body
    assert target == NotifyTarget("slack", "D1")


@pytest.mark.no_db
def test_several_questions_with_options_ask_for_one_line_each() -> None:
    """Decision Q-B: the notice says to answer one line per question."""
    notice, _ = question_notice(
        "spa_2",
        "sa_1",
        [
            "Which branch?",
            {"prompt": "Run tests?", "options": [{"label": "yes"}, {"label": "no"}]},
        ],
        ReplyDestination("telegram", "42", TELEGRAM),
        max_body_chars=3500,
    )

    body = notice.body
    assert body.index("Which branch?") < body.index("Run tests?")
    assert "yes" in body and "no" in body
    assert "Reply in this chat to answer." in body
    assert "one line per question" in body


@pytest.mark.no_db
def test_a_dm_destination_says_reply_in_this_chat() -> None:
    """Final review Important 1: an attached DM session -- the reply there is an answer."""
    notice, _ = question_notice(
        "spa_f1", "sa_1", ["Which branch?"], ReplyDestination("slack", "D1", SLACK), max_body_chars=3500
    )

    assert notice.body.rstrip().endswith("Reply in this chat to answer.")
    assert "direct message" not in notice.body


@pytest.mark.no_db
def test_a_notify_target_destination_asks_for_a_direct_message() -> None:
    """Final review Important 1: the notify target may be a group, where a reply is not an
    answer -- the footer names the rule that works (a DM to the bot)."""
    notice, target = question_notice(
        "spa_f2",
        "sa_1",
        ["Which branch?", "Run tests?"],
        ReplyDestination("slack", "C_general", None),
        max_body_chars=3500,
    )

    assert notice.body.rstrip().endswith("Reply to me in a direct message to answer.")
    assert "Reply in this chat" not in notice.body
    assert "one line per question" in notice.body
    assert target == NotifyTarget("slack", "C_general")


@pytest.mark.no_db
def test_a_long_notice_is_bounded() -> None:
    notice, _ = question_notice(
        "spa_3", "sa_1", ["x" * 400] * 4, ReplyDestination("slack", "D1", None), max_body_chars=300
    )

    assert len(notice.body) <= 300


@pytest.fixture(params=["memory", "postgres"])
async def notice_store(request):
    if request.param == "memory":
        return InMemoryNotificationStore({"sa_1": OWNER}), "sa_1"
    await _seed_owner()
    agent = await PostgresStandingAgentStore(db_manager.get_session).create(OWNER, "Dot")
    return PostgresNotificationStore(db_manager.get_session), agent.agent_id


async def _rows(store, agent_id):
    if isinstance(store, InMemoryNotificationStore):
        return [row for row in store.rows.values() if row["agent_id"] == agent_id]
    async with await db_manager.get_session() as session:
        result = await session.execute(
            text(
                "SELECT kind, dedupe_key, channel_type, channel_id, body "
                "FROM standing_notifications WHERE agent_id = :a"
            ),
            {"a": agent_id},
        )
        return [dict(row._mapping) for row in result]


@pytest.mark.asyncio
async def test_enqueue_to_writes_the_given_destination_without_a_notify_target(notice_store) -> None:
    store, agent_id = notice_store
    notice = StandingNotice(agent_id, "question_asked", "question:spa_x", "body")

    first = await store.enqueue_to(notice, NotifyTarget("telegram", "42"), now=NOW)
    second = await store.enqueue_to(notice, NotifyTarget("telegram", "42"), now=NOW)

    rows = await _rows(store, agent_id)
    assert (first, second) == (True, False)
    assert [(r["channel_type"], r["channel_id"], r["dedupe_key"]) for r in rows] == [
        ("telegram", "42", "question:spa_x")
    ]


@pytest.mark.asyncio
async def test_enqueue_question_twice_is_one_row(notice_store) -> None:
    store, agent_id = notice_store
    ask = _ask(["Which branch?"], reply_session_id=TELEGRAM)
    ask = replace(ask, agent_id=agent_id)

    assert await enqueue_question(store, ask, owner_id=OWNER, now=NOW, max_body_chars=3500) is True
    assert await enqueue_question(store, ask, owner_id=OWNER, now=NOW, max_body_chars=3500) is False

    rows = await _rows(store, agent_id)
    assert [(r["kind"], r["channel_type"], r["channel_id"]) for r in rows] == [
        ("question_asked", "telegram", "42")
    ]


@pytest.mark.asyncio
async def test_enqueue_question_without_a_session_goes_to_the_notify_target(notice_store) -> None:
    store, agent_id = notice_store
    await store.set_target(OWNER, agent_id, NotifyTarget("slack", "D_owner"))
    ask = _ask(["Which branch?"], reply_session_id=None)
    ask = replace(ask, agent_id=agent_id)

    assert await enqueue_question(store, ask, owner_id=OWNER, now=NOW, max_body_chars=3500) is True

    rows = await _rows(store, agent_id)
    assert [(r["channel_type"], r["channel_id"]) for r in rows] == [("slack", "D_owner")]


# ---- the same transaction (deviation 8) -------------------------------------------

ASK_INPUT = {"questions": ["Which branch?"]}
VALIDATED = CodingToolRegistry.default(command_allowlist=frozenset()).validate(
    "ask_user.v1", ASK_INPUT
)


async def _waiting_task():
    await _seed_owner()
    agent = await PostgresStandingAgentStore(db_manager.get_session).create(OWNER, "Dot")
    task = await PostgresCodingService(db_manager.get_session).create_task(
        owner_id=OWNER, prompt="p", mode=CodingTaskMode.AUTONOMOUS, agent_id=agent.agent_id
    )
    runs = PostgresCodingRunRepository(db_manager.get_session)
    run = await runs.ensure_run_started(
        task_id=task.task_id, instruction="p", development_mode=True, now=NOW
    )
    await runs.save_checkpoint(
        CodingCheckpoint(f"cc_{uuid4().hex}", task.task_id, run.run_id, 1, {"x": 1}, "rev", NOW)
    )
    lease = await runs.acquire_execution_lease(
        task_id=task.task_id,
        run_id=run.run_id,
        worker_id="w1",
        now=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    return runs, agent.agent_id, task.task_id, lease


async def _ask_with_notice(runs, agent_id, lease, ask_id, notice, target):
    return await runs.request_user_answer(
        lease=lease,
        tool_call=ToolCallCompleted("a1", "ask_user.v1", ASK_INPUT),
        validated=VALIDATED,
        loop_state={"x": 1},
        workspace_revision="rev",
        agent_id=agent_id,
        reply_session_id=TELEGRAM,
        reply_channel_type="telegram",
        asked_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        ask_id=ask_id,
        notice=notice,
        notice_target=target,
    )


async def _count(sql, **params):
    async with await db_manager.get_session() as session:
        return int((await session.execute(text(sql), params)).scalar_one())


@pytest.mark.asyncio
async def test_the_ask_and_its_notice_commit_together() -> None:
    runs, agent_id, task_id, lease = await _waiting_task()
    notice, target = question_notice(
        "spa_tx_1", agent_id, ["Which branch?"], ReplyDestination("telegram", "42", TELEGRAM),
        max_body_chars=3500,
    )

    commit = await _ask_with_notice(runs, agent_id, lease, "spa_tx_1", notice, target)

    assert commit.ask.ask_id == "spa_tx_1"
    rows = await _rows(PostgresNotificationStore(db_manager.get_session), agent_id)
    assert [(r["kind"], r["dedupe_key"], r["channel_id"]) for r in rows] == [
        ("question_asked", "question:spa_tx_1", "42")
    ]


@pytest.mark.asyncio
async def test_when_the_notice_cannot_be_written_neither_is_the_ask() -> None:
    runs, agent_id, task_id, lease = await _waiting_task()
    notice, _ = question_notice(
        "spa_tx_2", agent_id, ["Which branch?"], ReplyDestination("telegram", "42", TELEGRAM),
        max_body_chars=3500,
    )
    broken = SimpleNamespace(channel_type="telegram", channel_id=None)  # NOT NULL violation

    with pytest.raises(Exception):
        await _ask_with_notice(runs, agent_id, lease, "spa_tx_2", notice, broken)

    assert await _count("SELECT COUNT(*) FROM standing_pending_asks WHERE task_id = :t", t=task_id) == 0
    assert await _count(
        "SELECT COUNT(*) FROM coding_tasks WHERE task_id = :t AND status = 'running'", t=task_id
    ) == 1


@pytest.mark.asyncio
async def test_a_refused_ask_writes_no_notice() -> None:
    runs, agent_id, _task_id, lease = await _waiting_task()
    task2 = await PostgresCodingService(db_manager.get_session).create_task(
        owner_id=OWNER, prompt="p", mode=CodingTaskMode.AUTONOMOUS, agent_id=agent_id
    )
    run2 = await runs.ensure_run_started(
        task_id=task2.task_id, instruction="p", development_mode=True, now=NOW
    )
    lease2 = await runs.acquire_execution_lease(
        task_id=task2.task_id,
        run_id=run2.run_id,
        worker_id="w2",
        now=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    first, target = question_notice(
        "spa_tx_3", agent_id, ["a?"], ReplyDestination("telegram", "42", TELEGRAM), max_body_chars=3500
    )
    second, _ = question_notice(
        "spa_tx_4", agent_id, ["b?"], ReplyDestination("telegram", "42", TELEGRAM), max_body_chars=3500
    )
    await _ask_with_notice(runs, agent_id, lease, "spa_tx_3", first, target)

    assert await _ask_with_notice(runs, agent_id, lease2, "spa_tx_4", second, target) is None

    rows = await _rows(PostgresNotificationStore(db_manager.get_session), agent_id)
    assert [r["dedupe_key"] for r in rows] == ["question:spa_tx_3"]
