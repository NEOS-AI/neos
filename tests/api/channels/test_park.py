"""Busy inbound park/fold: at most one parked CHAT/PROMPT per session."""

from __future__ import annotations

import asyncio

import pytest

from neos.api.channels.gateway import ChannelGateway
from tests.api.channels.conftest import install_channel_settings
from tests.api.channels.test_gateway_router import FakeCoding, FakeWorkflow, _gateway, _message

pytestmark = pytest.mark.no_db


class _SlowWorkflow(FakeWorkflow):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.proceed = asyncio.Event()

    async def execute_workflow(self, payload, use_checkpointer=True):
        self.calls.append(payload)
        self.started.set()
        await self.proceed.wait()
        return {"final_response": f"done-{len(self.calls)}"}


class _RecordingAdapter:
    channel_type = "slack"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.got = asyncio.Event()

    async def send_response(
        self, channel_id: str, content: str, thread_id: str | None = None
    ) -> None:
        self.sent.append((channel_id, content, thread_id))
        self.got.set()


class _SlowCoding(FakeCoding):
    def __init__(self) -> None:
        super().__init__()
        self.steer_started = asyncio.Event()
        self.proceed = asyncio.Event()

    async def steer(self, *, task_id: str, owner_id: str, instruction: str) -> str:
        del owner_id
        self.steered.append((task_id, instruction))
        if len(self.steered) == 1:
            self.steer_started.set()
            await self.proceed.wait()
        return f"Steered {task_id}"


def _park_gateway(monkeypatch, *, workflow=None, coding=None):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    workflow = workflow or FakeWorkflow()
    coding = coding or FakeCoding()
    return ChannelGateway(workflow, coding=coding), workflow, coding


async def test_busy_unbound_chat_is_parked_not_dropped(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    assert gateway._inflight.acquire("sess-park") is True

    reply = await gateway.dispatch(_message("hello later", "sess-park"))

    assert "already working" not in reply.lower()
    assert "park" in reply.lower()
    assert workflow.calls == []
    assert coding.steered == []
    assert coding.started == []


async def test_parked_inbound_latest_wins_and_folds_after_unlock(monkeypatch):
    workflow = _SlowWorkflow()
    gateway, _, coding = _park_gateway(monkeypatch, workflow=workflow)
    adapter = _RecordingAdapter()
    gateway.register_adapter(adapter)

    first = asyncio.create_task(
        gateway.dispatch(_message("first turn", "sess-latest"))
    )
    await workflow.started.wait()

    parked_old = await gateway.dispatch(_message("stale follow-up", "sess-latest"))
    parked_new = await gateway.dispatch(_message("latest follow-up", "sess-latest"))

    assert "park" in parked_old.lower()
    assert "park" in parked_new.lower()
    assert len(workflow.calls) == 1

    workflow.proceed.set()
    first_reply = await first
    await asyncio.wait_for(adapter.got.wait(), timeout=1)

    assert first_reply.startswith("done-")
    assert len(workflow.calls) == 2
    assert "latest follow-up" in workflow.calls[1]["query"]
    assert "stale follow-up" not in workflow.calls[1]["query"]
    assert adapter.sent[-1][0] == "C"
    assert adapter.sent[-1][1].startswith("done-")
    assert coding.started == []


async def test_parked_bound_prompt_steers_after_unlock(monkeypatch):
    coding = _SlowCoding()
    gateway, workflow, _ = _park_gateway(monkeypatch, coding=coding)
    adapter = _RecordingAdapter()
    gateway.register_adapter(adapter)
    await gateway.dispatch(_message("/code fix auth", "sess-fold-bind"))

    first = asyncio.create_task(
        gateway.dispatch(_message("add logging", "sess-fold-bind"))
    )
    await coding.steer_started.wait()

    parked = await gateway.dispatch(_message("/plan cover tests", "sess-fold-bind"))
    assert "park" in parked.lower()
    assert coding.steered == [("ct_channel", "[U_alice] add logging")]

    coding.proceed.set()
    await first
    await asyncio.wait_for(adapter.got.wait(), timeout=1)

    assert coding.steered[0] == ("ct_channel", "[U_alice] add logging")
    assert "cover tests" in coding.steered[1][1]
    assert adapter.sent[-1][1] == "Steered ct_channel"
    assert workflow.calls == []


async def test_control_commands_bypass_park(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-ctrl-park"))
    assert gateway._inflight.acquire("sess-ctrl-park") is True

    status = await gateway.dispatch(_message("/status", "sess-ctrl-park"))
    stopped = await gateway.dispatch(_message("/stop", "sess-ctrl-park"))

    assert "queued" in status
    assert "Stopped" in stopped
    assert coding.stopped == ["ct_channel"]
    assert workflow.calls == []


async def test_code_while_inflight_is_not_parked(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)
    assert gateway._inflight.acquire("sess-code-busy") is True

    reply = await gateway.dispatch(_message("/code also this", "sess-code-busy"))

    assert "park" not in reply.lower()
    assert "already working" in reply.lower() or "drop" in reply.lower()
    assert coding.started == []
    assert workflow.calls == []


async def test_new_clears_parked_inbound(monkeypatch):
    workflow = _SlowWorkflow()
    gateway, _, _coding = _park_gateway(monkeypatch, workflow=workflow)

    first = asyncio.create_task(
        gateway.dispatch(_message("first turn", "sess-new-park"))
    )
    await workflow.started.wait()
    await gateway.dispatch(_message("please fold me", "sess-new-park"))
    reset = await gateway.dispatch(_message("/new", "sess-new-park"))
    assert reset == "Session reset."

    workflow.proceed.set()
    await first

    assert len(workflow.calls) == 1
    assert "please fold me" not in workflow.calls[0]["query"]
