"""Halt vs cancel vs drop must stay distinct in channel replies."""

from __future__ import annotations

import pytest

from neos.api.channels.replies import format_coding_status_reply
from tests.api.channels.test_gateway_router import _gateway, _message

pytestmark = pytest.mark.no_db


async def test_busy_non_chat_is_drop_not_failed_or_cancel(monkeypatch) -> None:
    gateway, workflow, coding = _gateway(monkeypatch)
    assert gateway._inflight.acquire("sess-drop") is True

    reply = await gateway.dispatch(_message("/code also this", "sess-drop"))

    assert reply.startswith("drop:")
    assert "cancel" not in reply
    assert "halt" not in reply
    assert "fail" not in reply.lower()
    assert coding.started == []
    assert workflow.calls == []


async def test_stop_reply_is_cancel_not_failed(monkeypatch) -> None:
    gateway, workflow, coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("/code do it", "sess-cancel"))

    reply = await gateway.dispatch(_message("/stop", "sess-cancel"))

    assert reply.startswith("cancel:")
    assert "fail" not in reply.lower()
    assert "Stopped" in reply
    assert coding.stopped == ["ct_channel"]
    assert workflow.calls == []


async def test_paused_status_is_halt_not_cancel(monkeypatch) -> None:
    class PausedCoding:
        async def status(self, *, task_id: str, owner_id: str) -> str:
            del owner_id
            return f"{task_id} paused"

    gateway, workflow, _coding = _gateway(monkeypatch)
    gateway._coding = PausedCoding()
    await gateway.bind_session("sess-halt", "ct_1", "u_owner")

    reply = await gateway.dispatch(_message("/status", "sess-halt"))

    assert reply.startswith("halt:")
    assert "paused" in reply
    assert "cancel" not in reply
    assert "fail" not in reply
    assert workflow.calls == []


def test_bridge_status_maps_paused_to_halt() -> None:
    reply = format_coding_status_reply("ct_1", "paused")
    assert reply.startswith("halt:")
    assert "paused" in reply
    assert "cancel" not in reply
    assert "fail" not in reply


def test_bridge_status_maps_cancelled_to_cancel_not_failed() -> None:
    reply = format_coding_status_reply("ct_1", "cancelled")
    assert reply.startswith("cancel:")
    assert "cancelled" in reply
    assert "fail" not in reply
    assert "halt" not in reply


def test_bridge_status_keeps_failed_distinct_from_cancel() -> None:
    reply = format_coding_status_reply("ct_1", "failed")
    assert "cancel" not in reply
    assert reply.endswith("failed")
