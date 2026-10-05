"""Q9c: the owner's DM answers a waiting agent question and resumes the task
(docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §7).

The real ChannelGateway, in-memory agent/thread/ask stores and the in-memory run
repository's `answer_user_question` (its Postgres twin is tested on the real DB in
tests/standing/test_ask_answer_repository.py). The resume callback is the one the
gateway is wired with in production minus the worker wake, which is recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.coding.domain.phases import CodingCheckpoint
from neos.config.schema import ChannelPrincipal
from neos.standing.ask_answers import ChannelAskAnswers, split_answers
from neos.standing.channel_threads import ChannelAgentThreads
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.threads import InMemoryAgentThreadStore
from tests.api.channels.conftest import install_channel_settings
from tests.coding.fakes import InMemoryCodingRunRepository

pytestmark = pytest.mark.no_db

OWNER = "u_alice"
OTHER = "u_bob"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SLACK_DM = "v2:slack:T1:D_alice:-"
TELEGRAM_DM = "v2:telegram:dm:42:-"
SLACK_ROOM = "v2:slack:T1:C_general:-"
PRINCIPALS = [
    ChannelPrincipal(platform="slack", platform_user_id="U_alice", user_id=OWNER),
    ChannelPrincipal(platform="telegram", platform_user_id="42", user_id=OWNER),
    ChannelPrincipal(platform="slack", platform_user_id="U_bob", user_id=OTHER),
]


class RecordingWorkflow:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute_workflow(self, payload, use_checkpointer=True):
        self.calls.append(payload)
        return {"final_response": f"reply {len(self.calls)}"}


def _settings(monkeypatch, *, ask: bool = True):
    installed = install_channel_settings(
        monkeypatch, allowed_users=["U_alice", "42", "U_bob"], principals=PRINCIPALS
    )
    standing = installed.config.standing_agents
    standing.enabled = True
    standing.threads.enabled = True
    standing.notifications.enabled = True
    standing.ask.enabled = ask
    return installed


def _slack(text, *, session=SLACK_DM, dm=True, user="U_alice", idem=""):
    return ChannelMessage(
        user_id=OWNER,
        session_id=session,
        text=text,
        channel_type="slack",
        channel_id=session.split(":")[3],
        metadata={"slack_user_id": user, "is_dm": dm, "idempotency_key": idem or f"s-{text}"},
    )


def _telegram(text, *, idem=""):
    return ChannelMessage(
        user_id=OWNER,
        session_id=TELEGRAM_DM,
        text=text,
        channel_type="telegram",
        channel_id="42",
        metadata={"telegram_user_id": 42, "is_dm": True, "idempotency_key": idem or f"t-{text}"},
    )


class World:
    def __init__(self) -> None:
        self.agents = InMemoryStandingAgentStore()
        self.threads = InMemoryAgentThreadStore(self.agents)
        self.runs = InMemoryCodingRunRepository(task_prompts={"ct_1": "p"})
        self.asks = self.runs.asks
        self.workflow = RecordingWorkflow()
        self.woken: list[tuple[str, str | None]] = []
        self.answers = ChannelAskAnswers(
            self.agents, self.threads, self.asks, resume=self._resume, clock=lambda: NOW
        )
        self.gateway = ChannelGateway(
            self.workflow,
            agent_threads=ChannelAgentThreads(self.agents, self.threads),
            ask_answers=self.answers,
        )

    async def _resume(self, ask, owner_id, answers, channel_type):
        commit = await self.runs.answer_user_question(
            ask_id=ask.ask_id,
            owner_id=owner_id,
            answers=answers,
            channel_type=channel_type,
            now=NOW,
        )
        if commit is not None:
            self.woken.append((ask.task_id, commit.checkpoint_id))
        return commit

    async def waiting(self, questions=("Which branch?",), *, reply_session_id=SLACK_DM):
        agent = await self.agents.create(OWNER, "Dot")
        self.runs.task_statuses["ct_1"] = "waiting_user"
        self.runs.task_owners["ct_1"] = OWNER
        self.runs.checkpoints.append(
            CodingCheckpoint("cc_ask", "ct_1", "cr_1", 7, {"x": 1}, "rev", NOW)
        )
        ask = await self.asks.open(
            agent_id=agent.agent_id,
            task_id="ct_1",
            run_id="cr_1",
            tool_call_id="a1",
            questions=list(questions),
            reply_session_id=reply_session_id,
            asked_at=NOW,
            expires_at=NOW + timedelta(hours=24),
        )
        return agent, ask


async def _turns(world, agent):
    thread = await world.threads.active(agent.agent_id)
    return [(t.role, t.session_id, t.content) for t in await world.threads.recent_turns(thread.agent_thread_id, limit=50)]


@pytest.mark.asyncio
async def test_an_answer_from_another_attached_channel_resumes(monkeypatch) -> None:
    """Review Focus 1: asked on Slack, answered from Telegram -> resumed once."""
    _settings(monkeypatch)
    world = World()
    agent, ask = await world.waiting()
    await world.threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await world.threads.attach_session(agent.agent_id, TELEGRAM_DM, "telegram")

    reply = await world.gateway.dispatch(_telegram("main"))

    assert reply.startswith("Answer recorded — resuming.")
    answered = await world.asks.for_call("ct_1", "cr_1", "a1")
    assert (answered.status, answered.answers) == ("answered", ("main",))
    assert world.runs.task_statuses["ct_1"] == "running"
    assert world.woken == [("ct_1", "cc_ask")]  # same run, latest checkpoint
    assert world.workflow.calls == []  # an answer is not a chat turn


@pytest.mark.asyncio
async def test_a_dm_not_yet_attached_still_answers(monkeypatch) -> None:
    """Deviation 1: asked through the notify target -- the DM attaches as it answers."""
    _settings(monkeypatch)
    world = World()
    agent, ask = await world.waiting(reply_session_id=None)

    reply = await world.gateway.dispatch(_slack("yes"))

    assert reply.startswith("Answer recorded")
    assert (await world.threads.thread_for_session(SLACK_DM)) is not None
    assert world.woken == [("ct_1", "cc_ask")]


@pytest.mark.asyncio
async def test_the_confirmation_carries_the_question(monkeypatch) -> None:
    """Review Focus 2: a stray message becomes the answer -- the reply says to what."""
    _settings(monkeypatch)
    world = World()
    await world.waiting(("Which branch should I deploy from?", "Run the slow tests?"))

    reply = await world.gateway.dispatch(_slack("lunch at noon?"))

    assert reply == (
        "Answer recorded — resuming.\n"
        "Q: Which branch should I deploy from? (+1 more)"
    )


@pytest.mark.asyncio
async def test_a_long_question_is_cut_in_the_confirmation(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting(("x" * 300,))

    reply = await world.gateway.dispatch(_slack("ok"))

    assert reply.splitlines()[1] == "Q: " + "x" * 119 + "…"


@pytest.mark.parametrize("text", ["/new", "/help", "/unknowncommand"])
@pytest.mark.asyncio
async def test_commands_are_not_answers(monkeypatch, text) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()

    reply = await world.gateway.dispatch(_slack(text))

    assert not reply.startswith("Answer recorded")
    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"
    assert world.woken == []


@pytest.mark.asyncio
async def test_a_group_channel_message_is_not_an_answer(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()

    await world.gateway.dispatch(_slack("main", session=SLACK_ROOM, dm=False))

    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"
    assert world.woken == []
    assert len(world.workflow.calls) == 1  # it went to the conversation, as today


@pytest.mark.asyncio
async def test_an_unmapped_sender_is_not_an_answer(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()

    await world.gateway.dispatch(_slack("main", user="U_stranger"))

    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"
    assert world.woken == []


@pytest.mark.asyncio
async def test_another_owners_dm_is_not_an_answer(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()
    await world.agents.create(OTHER, "Bob's Dot")

    await world.gateway.dispatch(_slack("main", session="v2:slack:T1:D_bob:-", user="U_bob"))

    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"
    assert world.woken == []


@pytest.mark.asyncio
async def test_a_coding_bound_session_is_not_an_answer(monkeypatch) -> None:
    """Deviation 2: a bound session's words steer its coding task."""
    _settings(monkeypatch)
    world = World()
    await world.waiting()
    await world.gateway.bind_session(SLACK_DM, "ct_bound", OWNER)
    steered = []

    async def steer(message, binding):
        steered.append(message.text)
        return "steered"

    world.gateway._steer_bound_chat = steer

    reply = await world.gateway.dispatch(_slack("main"))

    assert reply == "steered" and steered == ["main"]
    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"


@pytest.mark.asyncio
async def test_the_same_answer_retried_resumes_once(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()

    first = await world.gateway.dispatch(_slack("main", idem="ev-1"))
    again = await world.gateway.dispatch(_slack("main", idem="ev-1"))

    assert first == again
    assert world.woken == [("ct_1", "cc_ask")]


@pytest.mark.asyncio
async def test_after_the_answer_the_next_dm_is_a_chat_turn(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()

    await world.gateway.dispatch(_slack("main"))
    reply = await world.gateway.dispatch(_slack("thanks"))

    assert reply == "reply 1"
    assert len(world.woken) == 1


@pytest.mark.asyncio
async def test_a_task_no_longer_waiting_is_not_answered(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting()
    world.runs.task_statuses["ct_1"] = "cancelled"

    reply = await world.gateway.dispatch(_slack("main"))

    assert reply == "reply 1"
    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"
    assert world.woken == []


@pytest.mark.asyncio
async def test_with_the_flag_off_nothing_is_an_answer(monkeypatch) -> None:
    _settings(monkeypatch, ask=False)
    world = World()
    await world.waiting()

    reply = await world.gateway.dispatch(_slack("main"))

    assert reply == "reply 1"
    assert world.woken == []


@pytest.mark.asyncio
async def test_the_thread_gets_the_question_then_the_answer(monkeypatch) -> None:
    """Deviation 10: both turns are written by the API process when the answer lands."""
    _settings(monkeypatch)
    world = World()
    agent, ask = await world.waiting(("Which branch?", "Run tests?"), reply_session_id=SLACK_DM)
    await world.threads.attach_session(agent.agent_id, SLACK_DM, "slack")

    await world.gateway.dispatch(_telegram("1. main\n2. yes"))

    assert await _turns(world, agent) == [
        ("assistant", SLACK_DM, "1. Which branch?\n2. Run tests?"),
        ("user", TELEGRAM_DM, "1. main\n2. yes"),
    ]


@pytest.mark.asyncio
async def test_the_answer_reaches_the_ask_split_by_line(monkeypatch) -> None:
    _settings(monkeypatch)
    world = World()
    await world.waiting(("Which branch?", "Run tests?"))

    await world.gateway.dispatch(_slack("1. main\n2) yes"))

    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).answers == ("main", "yes")


# ---- the line-split rule (decision Q-B) -------------------------------------------


@pytest.mark.parametrize(
    ("text", "count", "expected"),
    [
        ("main", 1, ["main"]),
        ("  main\nand more  ", 1, ["main\nand more"]),
        ("main\nyes", 2, ["main", "yes"]),
        ("1. main\n\n2. yes\n", 2, ["main", "yes"]),
        ("1) main\n2) yes", 2, ["main", "yes"]),
        ("main", 2, ["main", "main"]),
        ("a\nb\nc", 2, ["a\nb\nc", "a\nb\nc"]),
    ],
)
def test_split_answers(text, count, expected) -> None:
    assert split_answers(text, count) == expected
