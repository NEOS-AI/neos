from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.config.schema import ChannelPrincipal
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db


class FakeWorkflow:
    def __init__(self, *, interrupt: bool = False) -> None:
        self.calls: list[object] = []
        self.interrupt = interrupt

    async def execute_workflow(self, payload, use_checkpointer=True):
        self.calls.append(payload)
        if self.interrupt:
            return {
                "success": True,
                "interrupted": True,
                "response": None,
                "pending_approvals": [
                    {"request_id": "apr_wf", "skill_name": "exec"}
                ],
            }
        return {"final_response": "workflow-ok"}


class FakeWorkflowApprovals:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    async def decide(self, *, session_id, request_id, owner_id, approve):
        del owner_id
        self.calls.append((session_id, request_id, approve))
        return f"{request_id} {'approved' if approve else 'denied'}"


class FakeCoding:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.stopped: list[str] = []
        self.steered: list[tuple[str, str]] = []
        self.decided: list[tuple[str, bool, str]] = []

    async def start_task(self, *, owner_id: str, prompt: str) -> str:
        self.started.append((owner_id, prompt))
        return "ct_channel"

    async def stop_task(self, *, task_id: str, owner_id: str) -> None:
        self.stopped.append(task_id)

    async def status(self, *, task_id: str, owner_id: str) -> str:
        return f"{task_id} queued"

    async def decide(self, *, task_id: str, owner_id: str, approve: bool, approval_id: str) -> str:
        self.decided.append((task_id, approve, approval_id))
        return f"{task_id} {'approved' if approve else 'denied'}"

    async def steer(self, *, task_id: str, owner_id: str, instruction: str) -> str:
        del owner_id
        self.steered.append((task_id, instruction))
        return f"Steered {task_id}"


def _message(
    text: str,
    session_id: str = "v2:slack:T:C:1",
    *,
    slack_user_id: str = "U_alice",
) -> ChannelMessage:
    return ChannelMessage(
        user_id="bot",
        session_id=session_id,
        text=text,
        channel_type="slack",
        channel_id="C",
        metadata={"slack_user_id": slack_user_id},
    )


def _gateway(
    monkeypatch,
    *,
    coding_invoke=True,
    owner="u_owner",
    principals=None,
):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=coding_invoke,
        coding_owner_user_id=owner,
        principals=principals,
    )
    workflow = FakeWorkflow()
    coding = FakeCoding()
    return ChannelGateway(workflow, coding=coding), workflow, coding


async def test_workflow_interrupt_returns_waiting_approval_card(monkeypatch):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    approvals = FakeWorkflowApprovals()
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
        workflow_approvals=approvals,
    )

    reply = await gateway.dispatch(_message("please run this"))
    decided = await gateway.dispatch(_message("/approve apr_wf"))

    assert reply == "v2:slack:T:C:1 waiting_approval apr_wf workflow"
    assert decided == "apr_wf approved"
    assert approvals.calls == [("v2:slack:T:C:1", "apr_wf", True)]


async def test_workflow_approve_without_port_is_not_fake_success(monkeypatch):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
    )

    reply = await gateway.dispatch(_message("please run this"))
    decided = await gateway.dispatch(_message("/approve apr_wf"))

    assert reply == "v2:slack:T:C:1 waiting_approval apr_wf workflow"
    assert "approved" not in decided.lower()
    assert "denied" not in decided.lower()
    assert "reject" not in decided.lower()
    assert "not configured" in decided.lower()


async def test_other_principal_cannot_approve_workflow(monkeypatch):
    principals = [
        ChannelPrincipal(
            platform="slack",
            platform_user_id="U_alice",
            user_id="u_alice",
        ),
        ChannelPrincipal(
            platform="slack",
            platform_user_id="U_eve",
            user_id="u_eve",
        ),
    ]
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice", "U_eve"],
        coding_invoke=True,
        coding_owner_user_id="u_shared",
        principals=principals,
    )
    approvals = FakeWorkflowApprovals()
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
        workflow_approvals=approvals,
    )

    reply = await gateway.dispatch(_message("please run this"))
    denied = await gateway.dispatch(
        _message("/approve apr_wf", slack_user_id="U_eve")
    )
    decided = await gateway.dispatch(_message("/approve apr_wf"))

    assert reply == "v2:slack:T:C:1 waiting_approval apr_wf workflow"
    assert denied == "Owner is not configured."
    assert approvals.calls == [("v2:slack:T:C:1", "apr_wf", True)]
    assert decided == "apr_wf approved"


async def test_workflow_approve_failure_keeps_pending(monkeypatch):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )

    class FailingThenOk:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool]] = []

        async def decide(self, *, session_id, request_id, owner_id, approve):
            del owner_id
            self.calls.append((session_id, request_id, approve))
            if len(self.calls) == 1:
                return "Failed to apply approval decision."
            return f"{request_id} {'approved' if approve else 'denied'}"

    approvals = FailingThenOk()
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
        workflow_approvals=approvals,
    )

    await gateway.dispatch(_message("please run this"))
    first = await gateway.dispatch(_message("/approve apr_wf"))
    second = await gateway.dispatch(_message("/approve apr_wf"))

    assert first == "Failed to apply approval decision."
    assert second == "apr_wf approved"
    assert approvals.calls == [
        ("v2:slack:T:C:1", "apr_wf", True),
        ("v2:slack:T:C:1", "apr_wf", True),
    ]


async def test_new_clears_ram_pending_approve_uses_checkpointer_port(monkeypatch):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    approvals = FakeWorkflowApprovals()
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
        workflow_approvals=approvals,
    )

    await gateway.dispatch(_message("please run this"))
    reset = await gateway.dispatch(_message("/new"))
    decided = await gateway.dispatch(_message("/approve apr_wf"))

    assert reset == "Session reset."
    assert await gateway.workflow_pending_owner("v2:slack:T:C:1") is None
    assert decided == "No coding task in this thread."
    assert approvals.calls == []


async def test_approve_without_ram_pending_uses_workflow_approvals(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    approvals = FakeWorkflowApprovals()
    gateway._workflow_approvals = approvals
    assert gateway._workflow_pending == {}

    decided = await gateway.dispatch(_message("/approve apr_x", "sess-ckpt"))

    assert decided == "apr_x approved"
    assert approvals.calls == [("sess-ckpt", "apr_x", True)]
    assert decided != "No coding task in this thread."
    assert workflow.calls == []
    assert coding.decided == []


async def test_checkpointer_approve_requires_interrupt_owner(monkeypatch):
    principals = [
        ChannelPrincipal(
            platform="slack",
            platform_user_id="U_alice",
            user_id="u_alice",
        ),
        ChannelPrincipal(
            platform="slack",
            platform_user_id="U_eve",
            user_id="u_eve",
        ),
    ]
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice", "U_eve"],
        coding_invoke=True,
        coding_owner_user_id="u_shared",
        principals=principals,
    )

    class OwnedApprovals(FakeWorkflowApprovals):
        async def interrupt_owner(self, session_id):
            del session_id
            return "u_alice"

    approvals = OwnedApprovals()
    gateway = ChannelGateway(
        FakeWorkflow(),
        coding=FakeCoding(),
        workflow_approvals=approvals,
    )
    denied = await gateway.dispatch(
        _message("/approve apr_x", "sess-ckpt", slack_user_id="U_eve")
    )
    decided = await gateway.dispatch(
        _message("/approve apr_x", "sess-ckpt", slack_user_id="U_alice")
    )
    assert denied == "Owner is not configured."
    assert decided == "apr_x approved"
    assert approvals.calls == [("sess-ckpt", "apr_x", True)]


async def test_stop_bypasses_held_inflight_on_bound_session(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-ctrl"))
    assert gateway._inflight.acquire("sess-ctrl") is True

    reply = await gateway.dispatch(_message("/stop", "sess-ctrl"))

    assert reply == "cancel: Stopped ct_channel"
    assert coding.stopped == ["ct_channel"]
    assert workflow.calls == []
    gateway._inflight.release("sess-ctrl")
    steered = await gateway.dispatch(_message("hello", "sess-ctrl"))
    assert steered == "Steered ct_channel"
    assert coding.steered == [("ct_channel", "[U_alice] hello")]


async def test_workflow_input_includes_channel_attachment_blocks(monkeypatch):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
        inbound_media=True,
    )
    workflow = FakeWorkflow()
    gateway = ChannelGateway(workflow, coding=FakeCoding())
    message = _message("see file")
    message.metadata["attachments"] = [
        {"name": "shot.png", "content_type": "image/png", "bytes": b"\x89PNG"}
    ]

    await gateway.dispatch(message)

    blocks = workflow.calls[0]["channel_attachments"]
    assert blocks[0]["kind"] == "IMAGE"
    assert blocks[0]["size"] == 4
    assert blocks[0]["data_b64"]
    assert "4 bytes" in workflow.calls[0]["query"]


async def test_plain_text_runs_workflow_not_coding(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("hello <@U_BOT>"))
    assert reply == "workflow-ok"
    assert workflow.calls
    assert coding.started == []


async def test_code_command_does_not_start_workflow(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("<@U_BOT> /code fix the test"))
    assert "ct_channel" in reply
    assert coding.started == [("u_owner", "[U_alice] fix the test")]
    assert workflow.calls == []


async def test_code_without_owner_or_flag_is_refused(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch, coding_invoke=False)
    reply = await gateway.dispatch(_message("/code fix"))
    assert "disabled" in reply.lower()
    assert coding.started == []
    assert workflow.calls == []


async def test_empty_code_is_usage(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("/code"))
    assert reply.startswith("Usage:")
    assert coding.started == []
    assert workflow.calls == []


async def test_stop_and_status_use_bound_task(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-1"))
    assert "queued" in await gateway.dispatch(_message("/status", "sess-1"))
    assert "Stopped" in await gateway.dispatch(_message("/stop", "sess-1"))
    assert coding.stopped == ["ct_channel"]
    assert await gateway.dispatch(_message("/status", "other")) == (
        "No coding task in this thread."
    )


async def test_code_uses_mapped_principal_not_shared_owner(monkeypatch):
    gateway, _workflow, coding = _gateway(
        monkeypatch,
        owner="u_shared",
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            )
        ],
    )
    reply = await gateway.dispatch(_message("<@U_BOT> /code fix the test"))
    assert "ct_channel" in reply
    assert coding.started == [("u_alice", "[U_alice] fix the test")]


async def test_code_without_principal_is_refused_when_map_exists(monkeypatch):
    gateway, _workflow, coding = _gateway(
        monkeypatch,
        owner="u_shared",
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            )
        ],
    )
    reply = await gateway.dispatch(
        _message("/code fix", slack_user_id="U_unknown")
    )
    assert "owner" in reply.lower()
    assert coding.started == []


async def test_chat_unmapped_principal_refuses_workflow_when_map_exists(monkeypatch):
    gateway, workflow, coding = _gateway(
        monkeypatch,
        owner="u_shared",
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            )
        ],
    )
    reply = await gateway.dispatch(
        _message("hello <@U_BOT>", slack_user_id="U_unknown")
    )
    assert "owner" in reply.lower()
    assert workflow.calls == []
    assert coding.started == []


async def test_chat_uses_bot_fallback_when_principals_empty(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("hello <@U_BOT>"))
    assert reply == "workflow-ok"
    assert workflow.calls[0]["user_id"] == "bot"
    assert coding.started == []


async def test_chat_uses_mapped_principal_when_map_exists(monkeypatch):
    gateway, workflow, coding = _gateway(
        monkeypatch,
        owner="u_shared",
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            )
        ],
    )
    reply = await gateway.dispatch(_message("hello <@U_BOT>"))
    assert reply == "workflow-ok"
    assert workflow.calls[0]["user_id"] == "u_alice"
    assert coding.started == []


async def test_duplicate_code_same_idempotency_key_starts_once(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    first = _message("<@U_BOT> /code fix the test")
    first.metadata["idempotency_key"] = "111.222"
    second = _message("<@U_BOT> /code fix the test")
    second.metadata["idempotency_key"] = "111.222"
    reply1 = await gateway.dispatch(first)
    reply2 = await gateway.dispatch(second)
    assert "ct_channel" in reply1
    assert "ct_channel" in reply2
    assert coding.started == [("u_owner", "[U_alice] fix the test")]
    assert workflow.calls == []


async def test_duplicate_chat_same_idempotency_key_runs_workflow_once(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    first = _message("hello <@U_BOT>")
    first.metadata["idempotency_key"] = "chat-1"
    second = _message("hello <@U_BOT>")
    second.metadata["idempotency_key"] = "chat-1"

    reply1 = await gateway.dispatch(first)
    reply2 = await gateway.dispatch(second)

    assert reply1 == "workflow-ok"
    assert reply2 == "workflow-ok"
    assert len(workflow.calls) == 1
    assert coding.started == []


async def test_duplicate_stop_same_idempotency_key_stops_once(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-stop-id"))
    first = _message("/stop", "sess-stop-id")
    first.metadata["idempotency_key"] = "stop-1"
    second = _message("/stop", "sess-stop-id")
    second.metadata["idempotency_key"] = "stop-1"

    reply1 = await gateway.dispatch(first)
    reply2 = await gateway.dispatch(second)

    assert reply1 == "cancel: Stopped ct_channel"
    assert reply2 == "cancel: Stopped ct_channel"
    assert coding.stopped == ["ct_channel"]
    assert workflow.calls == []


async def test_status_and_stop_same_card_ts_both_run(monkeypatch):
    gateway, _workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-card"))
    status = _message("/status", "sess-card")
    status.metadata["idempotency_key"] = "999.000:neos_code_status"
    stop = _message("/stop", "sess-card")
    stop.metadata["idempotency_key"] = "999.000:neos_code_stop"

    status_reply = await gateway.dispatch(status)
    stop_reply = await gateway.dispatch(stop)

    assert status_reply == "ct_channel queued"
    assert stop_reply == "cancel: Stopped ct_channel"
    assert coding.stopped == ["ct_channel"]


async def test_pending_claim_without_outcome_is_busy(monkeypatch):
    from neos.api.channels.inbound_idempotency import (
        InMemoryChannelInboundIdempotencyStore,
    )

    inbound = InMemoryChannelInboundIdempotencyStore()
    gateway, workflow, _coding = _gateway(monkeypatch)
    gateway._inbound = inbound
    await inbound.claim("sess-claim", "shared")
    message = _message("hello <@U_BOT>", "sess-claim")
    message.metadata["idempotency_key"] = "shared"

    reply = await gateway.dispatch(message)

    assert reply == "drop: Already working on this thread."
    assert workflow.calls == []


async def test_duplicate_approve_same_idempotency_key_decides_once(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-apr-id"))
    first = _message("/approve", "sess-apr-id")
    first.metadata["idempotency_key"] = "apr-1"
    second = _message("/approve", "sess-apr-id")
    second.metadata["idempotency_key"] = "apr-1"

    reply1 = await gateway.dispatch(first)
    reply2 = await gateway.dispatch(second)

    assert reply1 == "ct_channel approved"
    assert reply2 == "ct_channel approved"
    assert coding.decided == [("ct_channel", True, "")]
    assert workflow.calls == []


async def test_empty_idempotency_key_does_not_dedupe(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    first = _message("hello <@U_BOT>")
    first.metadata["idempotency_key"] = ""
    second = _message("hello <@U_BOT>")
    second.metadata["idempotency_key"] = ""

    reply1 = await gateway.dispatch(first)
    reply2 = await gateway.dispatch(second)

    assert reply1 == "workflow-ok"
    assert reply2 == "workflow-ok"
    assert len(workflow.calls) == 2
    assert coding.started == []


async def test_new_clears_inbound_so_same_key_can_run_again(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    first = _message("hello <@U_BOT>", "sess-clear")
    first.metadata["idempotency_key"] = "k1"
    replay = _message("hello again", "sess-clear")
    replay.metadata["idempotency_key"] = "k1"

    await gateway.dispatch(first)
    reset = await gateway.dispatch(_message("/new", "sess-clear"))
    reply = await gateway.dispatch(replay)

    assert reset == "Session reset."
    assert reply == "workflow-ok"
    assert len(workflow.calls) == 2


async def test_clear_does_not_wipe_inbound_idempotency(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    first = _message("hello <@U_BOT>", "sess-keep-id")
    first.metadata["idempotency_key"] = "k1"
    replay = _message("hello again", "sess-keep-id")
    replay.metadata["idempotency_key"] = "k1"

    assert await gateway.dispatch(first) == "workflow-ok"
    cleared = await gateway.dispatch(_message("/clear", "sess-keep-id"))
    reply = await gateway.dispatch(replay)

    assert "context" in cleared.lower()
    assert reply == "workflow-ok"
    assert len(workflow.calls) == 1


async def test_remembered_key_replays_while_other_key_is_inflight(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    first = _message("hello <@U_BOT>", "sess-busy-id")
    first.metadata["idempotency_key"] = "k1"
    replay = _message("hello <@U_BOT>", "sess-busy-id")
    replay.metadata["idempotency_key"] = "k1"
    other = _message("something else", "sess-busy-id")
    other.metadata["idempotency_key"] = "k2"

    assert await gateway.dispatch(first) == "workflow-ok"
    assert gateway._inflight.acquire("sess-busy-id") is True
    assert await gateway.dispatch(replay) == "workflow-ok"
    parked = await gateway.dispatch(other)
    assert "park" in parked.lower()
    assert len(workflow.calls) == 1


async def test_second_code_in_same_session_reuses_bound_task(monkeypatch):
    gateway, _workflow, coding = _gateway(monkeypatch)
    first = _message("<@U_BOT> /code one", "sess-a")
    first.metadata["idempotency_key"] = "1"
    second = _message("<@U_BOT> /code two", "sess-a")
    second.metadata["idempotency_key"] = "2"
    reply1 = await gateway.dispatch(first)
    reply2 = await gateway.dispatch(second)
    assert coding.started == [("u_owner", "[U_alice] one")]
    assert reply1 == reply2


async def test_code_prompt_includes_attachment_names(monkeypatch):
    gateway, _workflow, coding = _gateway(monkeypatch)
    message = _message("<@U_BOT> /code fix from screenshot")
    message.metadata["attachments"] = [
        {
            "name": "bug.png",
            "content_type": "image/png",
            "data": b"png",
        }
    ]
    await gateway.dispatch(message)
    assert coding.started[0][1].startswith("[U_alice] fix from screenshot")
    assert "bug.png" in coding.started[0][1]


async def test_workflow_query_includes_attachment_names(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    message = _message("hello <@U_BOT>")
    message.metadata["attachments"] = [
        {"name": "note.txt", "content_type": "text/plain", "data": b"hi"}
    ]
    await gateway.dispatch(message)
    assert workflow.calls[0]["query"].startswith("[U_alice] ")
    assert "note.txt" in workflow.calls[0]["query"]


async def test_coding_action_requires_mapped_owner(monkeypatch):
    from neos.api.channels.principals import coding_action_actor_allowed
    from neos.config.schema import ChannelPrincipal

    gateway, _workflow, _coding = _gateway(
        monkeypatch,
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            ),
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_eve",
                user_id="u_eve",
            ),
        ],
    )
    await gateway.bind_session("v2:slack:T:C:1", "ct_1", "u_alice")
    from neos.config.settings import settings

    allowed = await coding_action_actor_allowed(
        gateway=gateway,
        session_id="v2:slack:T:C:1",
        platform="slack",
        platform_user_id="U_alice",
        channels=settings.config.channels,
    )
    denied = await coding_action_actor_allowed(
        gateway=gateway,
        session_id="v2:slack:T:C:1",
        platform="slack",
        platform_user_id="U_eve",
        channels=settings.config.channels,
    )
    assert allowed is True
    assert denied is False


async def test_coding_action_requires_pending_workflow_owner(monkeypatch):
    from neos.api.channels.principals import coding_action_actor_allowed

    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice", "U_eve"],
        coding_invoke=True,
        coding_owner_user_id="u_shared",
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            ),
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_eve",
                user_id="u_eve",
            ),
        ],
    )
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
        workflow_approvals=FakeWorkflowApprovals(),
    )
    await gateway.dispatch(_message("please run this"))
    from neos.config.settings import settings

    allowed = await coding_action_actor_allowed(
        gateway=gateway,
        session_id="v2:slack:T:C:1",
        platform="slack",
        platform_user_id="U_alice",
        channels=settings.config.channels,
    )
    denied = await coding_action_actor_allowed(
        gateway=gateway,
        session_id="v2:slack:T:C:1",
        platform="slack",
        platform_user_id="U_eve",
        channels=settings.config.channels,
    )
    unbound = await coding_action_actor_allowed(
        gateway=gateway,
        session_id="v2:slack:T:C:other",
        platform="slack",
        platform_user_id="U_eve",
        channels=settings.config.channels,
    )
    assert allowed is True
    assert denied is False
    assert unbound is False


async def test_runtime_workflow_approvals_resumes_without_coding_loop(monkeypatch):
    import asyncio

    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    graph = _FakeResumeGraph(
        values={"pending_approvals": [{"request_id": "apr_1"}]}
    )

    class FakeWF:
        def __init__(self) -> None:
            self.graph = graph
            self._graph_initialized = True
            self._graph_uses_checkpointer = True

    async def _resume_graph_for(state_values, *, workflow, checkpointer):
        del state_values, workflow, checkpointer
        return graph

    marked: list[tuple[str, str]] = []

    async def _mark(request_id: str, user_id: str) -> None:
        marked.append((request_id, user_id))

    monkeypatch.setattr(
        "neos.workflow.resume_graph.resume_graph_for", _resume_graph_for
    )
    monkeypatch.setattr(
        "neos.api.channels.workflow_approvals._mark_resolved_best_effort",
        _mark,
    )

    port = RuntimeWorkflowApprovals(FakeWF())
    result = await port.decide(
        session_id="sess-1",
        request_id="apr_1",
        owner_id="u_alice",
        approve=True,
    )
    denied = await port.decide(
        session_id="sess-1",
        request_id="missing",
        owner_id="u_alice",
        approve=False,
    )
    await asyncio.sleep(0)

    assert result == "apr_1 approved"
    assert "approved" not in denied.lower()
    assert graph.updated == [
        (
            {"configurable": {"thread_id": "sess-1"}},
            {
                "approval_decision": "approved",
                "pending_approvals": [],
            },
        )
    ]
    assert graph.streamed
    assert marked == [("apr_1", "u_alice")]
    replay = await port.decide(
        session_id="sess-1",
        request_id="apr_1",
        owner_id="u_alice",
        approve=True,
    )
    assert "approved" not in replay.lower()
    assert len(graph.updated) == 1


async def test_runtime_workflow_approvals_missing_graph_is_not_success():
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    class FakeWF:
        graph = None
        _graph_initialized = False
        _graph_uses_checkpointer = False

    result = await RuntimeWorkflowApprovals(FakeWF()).decide(
        session_id="sess-1",
        request_id="apr_1",
        owner_id="u_alice",
        approve=True,
    )
    assert "approved" not in result.lower()


class _FakeResumeGraph:
    def __init__(self, *, values) -> None:
        self.values = values
        self.checkpointer = object()
        self.updated: list[tuple[object, object]] = []
        self.streamed: list[tuple[object, object]] = []

    async def aget_state(self, config):
        del config
        return SimpleNamespace(values=self.values)

    async def aupdate_state(self, *, config, values):
        self.updated.append((config, values))
        self.values = {**self.values, **values}

    async def astream(self, inp, config=None):
        self.streamed.append((inp, config))
        if False:
            yield {}


async def test_inflight_second_message_is_parked(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    assert gateway._inflight.acquire("sess-busy") is True
    reply = await gateway.dispatch(_message("hello", "sess-busy"))
    assert "park" in reply.lower()
    assert "already working" not in reply.lower()
    assert workflow.calls == []


async def test_bound_chat_parks_while_inflight(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code fix auth", "sess-busy-bind"))
    assert gateway._inflight.acquire("sess-busy-bind") is True
    reply = await gateway.dispatch(_message("also add tests", "sess-busy-bind"))
    assert "park" in reply.lower()
    assert coding.steered == []
    assert workflow.calls == []


async def test_learn_persists_via_postgres_when_factory_set(monkeypatch):
    import neos.config.settings as settings_module
    from neos.learn.lessons import LessonStatus, reset_lesson_store

    store = reset_lesson_store()
    gateway, workflow, coding = _gateway(monkeypatch)
    monkeypatch.setattr(settings_module.settings.config.learn, "coding_lessons", True)
    assert settings_module.settings.config.learn.channel_learn is False

    added: list[object] = []

    class FakePostgresLessonStore:
        def __init__(self, factory) -> None:
            self.factory = factory

        async def add(self, lesson):
            added.append(lesson)
            return lesson

    monkeypatch.setattr(
        "neos.coding.learn_lessons.resolve_lesson_session_factory",
        lambda: object(),
    )
    monkeypatch.setattr(
        "neos.coding.learn_lessons.PostgresLessonStore",
        FakePostgresLessonStore,
    )

    reply = await gateway.dispatch(_message("/learn the rate limit is 60"))

    assert reply == "Lesson staged."
    assert len(added) == 1
    assert added[0].status is LessonStatus.STAGED
    assert "rate limit is 60" in added[0].body
    assert store.list() == ()
    assert workflow.calls == []
    assert coding.started == []


async def test_chat_after_code_steers_bound_task(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    started = await gateway.dispatch(_message("/code fix auth", "sess-steer"))
    reply = await gateway.dispatch(_message("please also add tests", "sess-steer"))

    assert "ct_channel" in started
    assert reply == "Steered ct_channel"
    assert coding.steered == [("ct_channel", "[U_alice] please also add tests")]
    assert workflow.calls == []


async def test_chat_without_bind_still_runs_workflow(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("hello <@U_BOT>"))

    assert reply == "workflow-ok"
    assert workflow.calls
    assert coding.steered == []


async def test_new_then_chat_runs_workflow_again(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-new-chat"))
    reset = await gateway.dispatch(_message("/new", "sess-new-chat"))
    reply = await gateway.dispatch(_message("hello again", "sess-new-chat"))

    assert reset == "Session reset."
    assert reply == "workflow-ok"
    assert workflow.calls
    assert coding.steered == []


async def test_clear_does_not_stop_or_unbind_coding_task(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    started = await gateway.dispatch(_message("/code do it", "sess-clear-keep"))
    reply = await gateway.dispatch(_message("/clear", "sess-clear-keep"))
    status = await gateway.dispatch(_message("/status", "sess-clear-keep"))
    steered = await gateway.dispatch(_message("keep going", "sess-clear-keep"))

    assert "ct_channel" in started
    assert "context" in reply.lower()
    assert "reset" not in reply.lower()
    assert coding.stopped == []
    assert "queued" in status
    assert steered == "Steered ct_channel"
    assert workflow.calls == []


async def test_clear_drops_workflow_pending_without_session_reset(monkeypatch):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    approvals = FakeWorkflowApprovals()
    gateway = ChannelGateway(
        FakeWorkflow(interrupt=True),
        coding=FakeCoding(),
        workflow_approvals=approvals,
    )

    await gateway.dispatch(_message("please run this", "sess-clear-wf"))
    cleared = await gateway.dispatch(_message("/clear", "sess-clear-wf"))
    decided = await gateway.dispatch(_message("/approve apr_wf", "sess-clear-wf"))

    assert "context" in cleared.lower()
    assert await gateway.get_binding("sess-clear-wf") is None
    assert decided == "apr_wf approved"
    assert approvals.calls == [("sess-clear-wf", "apr_wf", True)]


async def test_compact_cost_export_bypass_held_inflight(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-ctrl-slash"))
    assert gateway._inflight.acquire("sess-ctrl-slash") is True

    compact = await gateway.dispatch(_message("/compact shrink", "sess-ctrl-slash"))
    cost = await gateway.dispatch(_message("/cost", "sess-ctrl-slash"))
    export = await gateway.dispatch(_message("/export", "sess-ctrl-slash"))

    assert "not available" in compact.lower() or "queued" in compact.lower()
    assert "success" not in compact.lower()
    assert "compacted" not in compact.lower()
    assert "cost" in cost.lower() or "token" in cost.lower()
    assert "code ui" in export.lower()
    assert "secret" not in export.lower()
    assert coding.started == [("u_owner", "[U_alice] do it")]
    assert workflow.calls == []


async def test_compact_without_task_does_not_start_loop(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("/compact shrink", "sess-no-task"))

    assert reply == "No coding task in this thread."
    assert coding.started == []
    assert workflow.calls == []


async def test_compact_calls_existing_port_method_when_present(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    called: list[tuple[str, str, str]] = []

    async def compact(*, task_id: str, owner_id: str, instruction: str) -> str:
        called.append((task_id, owner_id, instruction))
        return f"Compact requested for {task_id}"

    coding.compact = compact
    await gateway.dispatch(_message("/code do it", "sess-compact"))
    reply = await gateway.dispatch(_message("/compact keep plan", "sess-compact"))

    assert reply == "Compact requested for ct_channel"
    assert called == [("ct_channel", "u_owner", "keep plan")]
    assert workflow.calls == []
    assert coding.started == [("u_owner", "[U_alice] do it")]


async def test_cost_includes_snapshot_fields_when_readable(monkeypatch):
    gateway, _workflow, coding = _gateway(monkeypatch)

    async def snapshot(*, task_id: str, owner_id: str):
        del owner_id
        return SimpleNamespace(
            latest_checkpoint=SimpleNamespace(
                loop_state={
                    "cost_micros": 2500,
                    "input_tokens": 11,
                    "output_tokens": 7,
                }
            )
        )

    coding.snapshot = snapshot
    await gateway.dispatch(_message("/code do it", "sess-cost"))
    reply = await gateway.dispatch(_message("/cost", "sess-cost"))

    assert "2500" in reply
    assert "11" in reply
    assert "7" in reply


async def test_export_does_not_dump_transcript(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-export"))
    reply = await gateway.dispatch(_message("/export", "sess-export"))

    assert "code ui" in reply.lower()
    assert "SECRET" not in reply
    assert "loop_state" not in reply
    assert workflow.calls == []
    assert coding.started == [("u_owner", "[U_alice] do it")]


async def test_loop_is_denied_and_does_not_steer(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-loop"))
    reply = await gateway.dispatch(_message("/loop 5m check deploy", "sess-loop"))

    assert "disabled" in reply.lower()
    assert coding.steered == []
    assert workflow.calls == []


async def test_unknown_slash_does_not_start_workflow(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("/not-a-command", "sess-unknown"))

    assert "unknown command" in reply.lower()
    assert workflow.calls == []
    assert coding.started == []


async def test_help_lists_commands_without_task(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("/help", "sess-help"))

    assert "/compact" in reply
    assert "/loop" in reply
    assert workflow.calls == []


async def test_plan_steers_expanded_prompt(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-plan"))
    reply = await gateway.dispatch(_message("/plan auth", "sess-plan"))

    assert "Steered" in reply
    assert coding.steered
    assert coding.steered[-1][1].startswith("[U_alice] Switch to plan")
    assert "auth" in coding.steered[-1][1]
    assert workflow.calls == []
