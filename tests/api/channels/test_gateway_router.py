from __future__ import annotations

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db


class FakeWorkflow:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def execute_workflow(self, payload, use_checkpointer=True):
        self.calls.append(payload)
        return {"final_response": "workflow-ok"}


class FakeCoding:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.stopped: list[str] = []

    async def start_task(self, *, owner_id: str, prompt: str) -> str:
        self.started.append((owner_id, prompt))
        return "ct_channel"

    async def stop_task(self, *, task_id: str, owner_id: str) -> None:
        self.stopped.append(task_id)

    async def status(self, *, task_id: str, owner_id: str) -> str:
        return f"{task_id} queued"

    async def decide(self, *, task_id: str, owner_id: str, approve: bool, approval_id: str) -> str:
        return f"{task_id} {'approved' if approve else 'denied'}"


def _message(text: str, session_id: str = "v2:slack:T:C:1") -> ChannelMessage:
    return ChannelMessage(
        user_id="bot",
        session_id=session_id,
        text=text,
        channel_type="slack",
        channel_id="C",
    )


def _gateway(monkeypatch, *, coding_invoke=True, owner="u_owner"):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=coding_invoke,
        coding_owner_user_id=owner,
    )
    workflow = FakeWorkflow()
    coding = FakeCoding()
    return ChannelGateway(workflow, coding=coding), workflow, coding


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
    assert coding.started == [("u_owner", "fix the test")]
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


async def test_inflight_second_message_is_dropped(monkeypatch):
    gateway, workflow, _coding = _gateway(monkeypatch)
    assert gateway._inflight.acquire("sess-busy") is True
    reply = await gateway.dispatch(_message("hello", "sess-busy"))
    assert reply == "Already working on this thread."
    assert workflow.calls == []
