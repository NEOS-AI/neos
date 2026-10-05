"""Q8b: the real ChannelGateway carries an agent's DM turns across channels
(docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §5-§8).

In-memory agent and thread stores (their Postgres twins share one contract,
tests/standing/test_agent_threads_contract.py); the workflow is a fake that
records its payload, so the assertions read exactly what the workflow saw.
"""

from __future__ import annotations

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.config.schema import ChannelPrincipal
from neos.standing.channel_threads import ChannelAgentThreads
from neos.standing.models import StandingAgentStatus
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.threads import InMemoryAgentThreadStore, thread_window
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db

OWNER = "u_alice"
SLACK_DM = "v2:slack:T1:D_alice:-"
TELEGRAM_DM = "v2:telegram:dm:42:-"
SLACK_ROOM = "v2:slack:T1:C_general:-"

PRINCIPALS = [
    ChannelPrincipal(platform="slack", platform_user_id="U_alice", user_id=OWNER),
    ChannelPrincipal(platform="telegram", platform_user_id="42", user_id=OWNER),
]


class RecordingWorkflow:
    def __init__(self, *, interrupt: bool = False, reply: str = "") -> None:
        self.calls: list[dict] = []
        self.interrupt = interrupt
        self.reply = reply

    async def execute_workflow(self, payload, use_checkpointer=True):
        self.calls.append(payload)
        if self.interrupt:
            return {
                "interrupted": True,
                "pending_approvals": [{"request_id": "apr_1"}],
            }
        return {"final_response": self.reply or f"reply {len(self.calls)}"}


class ExplodingThreads:
    """Every call fails -- the thread must never block the conversation."""

    def __getattr__(self, name):
        async def boom(*args, **kwargs):
            raise RuntimeError(f"thread store down ({name})")

        return boom


class UntouchableThreads:
    """Records every call. Raising would not do: the gateway swallows thread errors on
    purpose (the thread never blocks the conversation), so a raise would pass silently."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        async def record(*args, **kwargs):
            self.calls.append(name)
            return None

        return record


def _settings(monkeypatch, *, threads: bool = True, standing: bool = True, principals=PRINCIPALS):
    installed = install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice", "42"],
        principals=principals,
    )
    installed.config.standing_agents.enabled = standing
    installed.config.standing_agents.threads.enabled = threads
    return installed


def _slack(text: str, *, session: str = SLACK_DM, dm: bool = True, user: str = "U_alice", idem: str = "") -> ChannelMessage:
    return ChannelMessage(
        user_id=OWNER,
        session_id=session,
        text=text,
        channel_type="slack",
        channel_id=session.split(":")[3],
        metadata={"slack_user_id": user, "is_dm": dm, "idempotency_key": idem or f"s-{text}"},
    )


def _telegram(text: str, *, idem: str = "") -> ChannelMessage:
    return ChannelMessage(
        user_id=OWNER,
        session_id=TELEGRAM_DM,
        text=text,
        channel_type="telegram",
        channel_id="42",
        metadata={"telegram_user_id": 42, "is_dm": True, "idempotency_key": idem or f"t-{text}"},
    )


async def _wired(workflow=None, *, status=StandingAgentStatus.ACTIVE):
    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    agent = await agents.create(OWNER, "Dot")
    if status is not StandingAgentStatus.ACTIVE:
        await agents.update(OWNER, agent.agent_id, status=status)
    workflow = workflow or RecordingWorkflow()
    gateway = ChannelGateway(workflow, agent_threads=ChannelAgentThreads(agents, threads))
    return gateway, workflow, threads, agent


# ---- F10: one context across channels ------------------------------------------


@pytest.mark.asyncio
async def test_a_slack_dm_turn_is_in_the_next_telegram_turn(monkeypatch) -> None:
    _settings(monkeypatch)
    gateway, workflow, _threads, _agent = await _wired()

    await gateway.dispatch(_slack("remember the launch is friday"))
    await gateway.dispatch(_telegram("when is the launch?"))

    assert "chat_history" in workflow.calls[0] and workflow.calls[0]["chat_history"] == []
    history = workflow.calls[1]["chat_history"]
    assert [(h["role"], h["content"]) for h in history] == [
        ("user", "[slack] remember the launch is friday"),
        ("assistant", "[slack] reply 1"),
    ]
    # The current turn rides in `query`, never twice in the history.
    assert "when is the launch?" in workflow.calls[1]["query"]


@pytest.mark.asyncio
async def test_turns_from_the_same_channel_carry_no_label(monkeypatch) -> None:
    _settings(monkeypatch)
    gateway, workflow, _threads, _agent = await _wired()

    await gateway.dispatch(_slack("first"))
    await gateway.dispatch(_slack("second"))

    assert [h["content"] for h in workflow.calls[1]["chat_history"]] == ["first", "reply 1"]


@pytest.mark.asyncio
async def test_the_thread_stores_what_the_owner_saw(monkeypatch) -> None:
    _settings(monkeypatch)
    gateway, _workflow, threads, agent = await _wired(RecordingWorkflow(reply="Friday."))

    reply = await gateway.dispatch(_slack("launch?"))

    active = await threads.get_or_create_active(agent.agent_id)
    turns = await thread_window(threads, active.agent_thread_id, limit=10)
    assert reply == "Friday."
    assert [(t.role, t.content, t.channel_type) for t in turns] == [
        ("user", "launch?", "slack"),
        ("assistant", "Friday.", "slack"),
    ]


# ---- §5: what never attaches -- the payload stays as it was ---------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_slack("hi", session=SLACK_ROOM, dm=False), id="group-channel"),
        pytest.param(_slack("hi", user="U_eve"), id="unmapped-sender"),
        pytest.param(
            ChannelMessage(
                user_id=OWNER, session_id=SLACK_DM, text="hi", channel_type="slack",
                channel_id="D_alice", metadata={"slack_user_id": "U_alice"},
            ),
            id="is-dm-missing",
        ),
    ],
)
async def test_sessions_that_never_attach(monkeypatch, message) -> None:
    _settings(monkeypatch)
    gateway, workflow, threads, agent = await _wired()

    await gateway.dispatch(message)

    # An unmapped sender is refused before the workflow runs (`_NO_OWNER`); the
    # others run without a history. Either way the thread is untouched.
    assert all("chat_history" not in call for call in workflow.calls)
    assert await threads.list_threads(agent.agent_id) == []


@pytest.mark.asyncio
async def test_without_principals_nothing_attaches(monkeypatch) -> None:
    """The gateway's user_id is unmapped when principals are empty -- not an owner."""
    _settings(monkeypatch, principals=[])
    gateway, workflow, threads, agent = await _wired()

    await gateway.dispatch(_slack("hi"))

    assert "chat_history" not in workflow.calls[0]
    assert await threads.list_threads(agent.agent_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [StandingAgentStatus.PAUSED, StandingAgentStatus.RETIRED])
async def test_a_paused_or_retired_agent_writes_no_turns(monkeypatch, status) -> None:
    _settings(monkeypatch)
    gateway, workflow, threads, agent = await _wired(status=status)

    reply = await gateway.dispatch(_slack("hi"))

    assert reply == "reply 1"  # the conversation itself is not blocked
    assert "chat_history" not in workflow.calls[0]
    assert await threads.list_threads(agent.agent_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("standing", "threads_on"), [(True, False), (False, True)])
async def test_flags_off_never_touch_the_store(monkeypatch, standing, threads_on) -> None:
    _settings(monkeypatch, standing=standing, threads=threads_on)
    agents = InMemoryStandingAgentStore()
    await agents.create(OWNER, "Dot")
    workflow = RecordingWorkflow()
    untouchable = UntouchableThreads()
    gateway = ChannelGateway(
        workflow, agent_threads=ChannelAgentThreads(agents, untouchable)
    )

    await gateway.dispatch(_slack("hi"))
    await gateway.dispatch(_slack("/new", idem="n1"))

    assert "chat_history" not in workflow.calls[0]
    assert untouchable.calls == []


@pytest.mark.asyncio
async def test_a_bound_coding_session_steers_and_writes_no_turn(monkeypatch) -> None:
    _settings(monkeypatch)

    class Steering:
        def __init__(self):
            self.steered = []

        async def steer(self, *, task_id, owner_id, instruction):
            self.steered.append(instruction)
            return "steered"

    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    agent = await agents.create(OWNER, "Dot")
    coding = Steering()
    workflow = RecordingWorkflow()
    gateway = ChannelGateway(
        workflow, coding=coding, agent_threads=ChannelAgentThreads(agents, threads)
    )
    await gateway.bind_session(SLACK_DM, "ct_1", OWNER)

    assert await gateway.dispatch(_slack("go on")) == "steered"
    assert workflow.calls == []
    assert await threads.list_threads(agent.agent_id) == []


# ---- §8: the thread never blocks the conversation -------------------------------


@pytest.mark.asyncio
async def test_a_failing_thread_store_still_answers_and_is_counted(monkeypatch) -> None:
    from neos.observability.metrics import metrics

    _settings(monkeypatch)
    agents = InMemoryStandingAgentStore()
    await agents.create(OWNER, "Dot")
    workflow = RecordingWorkflow(reply="still here")
    gateway = ChannelGateway(
        workflow, agent_threads=ChannelAgentThreads(agents, ExplodingThreads())
    )
    counter = metrics.standing_thread_failures_total.labels(op="open")
    before = counter._value.get()

    assert await gateway.dispatch(_slack("hi")) == "still here"
    assert "chat_history" not in workflow.calls[0]
    assert counter._value.get() == before + 1


@pytest.mark.asyncio
async def test_an_interrupted_turn_records_only_the_user_side(monkeypatch) -> None:
    """The owner saw a waiting-approval card, not an answer -- no assistant turn."""
    _settings(monkeypatch)
    gateway, _workflow, threads, agent = await _wired(RecordingWorkflow(interrupt=True))

    reply = await gateway.dispatch(_slack("delete the old branch"))

    active = await threads.get_or_create_active(agent.agent_id)
    turns = await thread_window(threads, active.agent_thread_id, limit=10)
    assert "waiting_approval" in reply
    assert [(t.role, t.content) for t in turns] == [("user", "delete the old branch")]


# ---- §7: /new rotates the agent's thread for every channel ----------------------


@pytest.mark.asyncio
async def test_new_on_slack_starts_telegram_fresh_too(monkeypatch) -> None:
    _settings(monkeypatch)
    gateway, workflow, threads, agent = await _wired()
    await gateway.dispatch(_slack("old topic"))
    await gateway.dispatch(_telegram("still old"))
    before = await threads.get_or_create_active(agent.agent_id)

    reply = await gateway.dispatch(_slack("/new", idem="n1"))
    await gateway.dispatch(_telegram("new topic"))

    assert "every channel" in reply
    assert workflow.calls[-1]["chat_history"] == []
    after = await threads.get_or_create_active(agent.agent_id)
    assert after.agent_thread_id != before.agent_thread_id
    # The old transcript is archived, not deleted.
    assert len(await thread_window(threads, before.agent_thread_id, limit=10)) == 4


@pytest.mark.asyncio
async def test_new_in_an_unattached_session_is_a_plain_reset(monkeypatch) -> None:
    _settings(monkeypatch)
    gateway, _workflow, threads, agent = await _wired()

    reply = await gateway.dispatch(_slack("/new", session=SLACK_ROOM, dm=False, idem="n1"))

    assert reply == "Session reset."
    assert await threads.list_threads(agent.agent_id) == []


@pytest.mark.asyncio
async def test_new_does_not_rotate_someone_elses_agent(monkeypatch) -> None:
    """A session attached to Alice's agent; Eve (mapped to another user, with an agent
    of her own) types /new in it -- impossible in a real DM, so the rule is checked
    directly. Neither agent rotates."""
    principals = PRINCIPALS + [
        ChannelPrincipal(platform="slack", platform_user_id="U_eve", user_id="u_eve")
    ]
    _settings(monkeypatch, principals=principals)
    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    alice = await agents.create(OWNER, "Dot")
    eve = await agents.create("u_eve", "Eve's")
    gateway = ChannelGateway(
        RecordingWorkflow(), agent_threads=ChannelAgentThreads(agents, threads)
    )
    await gateway.dispatch(_slack("mine"))
    alice_before = await threads.get_or_create_active(alice.agent_id)
    eve_before = await threads.get_or_create_active(eve.agent_id)

    reply = await gateway.dispatch(_slack("/new", user="U_eve", idem="n1"))

    assert reply == "Session reset."
    assert await threads.get_or_create_active(alice.agent_id) == alice_before
    assert await threads.get_or_create_active(eve.agent_id) == eve_before
