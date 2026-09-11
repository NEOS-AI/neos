from __future__ import annotations

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.api.channels.session_bind import InMemoryChannelCodingBindStore
from tests.api.channels.conftest import install_channel_settings
from tests.api.channels.test_gateway_router import FakeCoding, FakeWorkflow, _message

pytestmark = pytest.mark.no_db


def _gateway(monkeypatch, *, binds=None, coding=None, workflow=None):
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    workflow = workflow or FakeWorkflow()
    coding = coding or FakeCoding()
    return (
        ChannelGateway(workflow, coding=coding, binds=binds),
        workflow,
        coding,
    )


async def test_in_memory_bind_is_visible_across_store_clients() -> None:
    store = InMemoryChannelCodingBindStore()
    await store.bind("v2:slack:T:C:1", "ct_shared", "u_owner")

    found = await store.get("v2:slack:T:C:1")

    assert found is not None
    assert found.session_id == "v2:slack:T:C:1"
    assert found.task_id == "ct_shared"
    assert found.owner_id == "u_owner"


async def test_in_memory_bind_is_visible_by_task_id() -> None:
    store = InMemoryChannelCodingBindStore()
    await store.bind("v2:slack:T:C:1", "ct_shared", "u_owner")

    found = await store.get_by_task("ct_shared")

    assert found is not None
    assert found.session_id == "v2:slack:T:C:1"


async def test_bind_from_gateway_a_is_visible_to_gateway_b(monkeypatch):
    store = InMemoryChannelCodingBindStore()
    coding = FakeCoding()
    first, _, _ = _gateway(monkeypatch, binds=store, coding=coding)
    second, workflow, _ = _gateway(monkeypatch, binds=store, coding=coding)

    started = await first.dispatch(_message("/code fix auth", "v2:slack:T:C:9"))
    stopped = await second.dispatch(_message("/stop", "v2:slack:T:C:9"))

    assert "ct_channel" in started
    assert stopped == "Stopped ct_channel"
    assert coding.stopped == ["ct_channel"]
    assert workflow.calls == []


async def test_stop_without_bind_reports_no_task(monkeypatch):
    gateway, workflow, coding = _gateway(monkeypatch)

    reply = await gateway.dispatch(_message("/stop"))

    assert reply == "No coding task in this thread."
    assert coding.stopped == []
    assert workflow.calls == []


async def test_code_then_new_gateway_stop_uses_persisted_task_id(monkeypatch):
    store = InMemoryChannelCodingBindStore()
    coding = FakeCoding()
    first, _, _ = _gateway(monkeypatch, binds=store, coding=coding)
    await first.dispatch(_message("/code do it", "sess-persist"))

    second, workflow, _ = _gateway(monkeypatch, binds=store, coding=coding)
    reply = await second.dispatch(_message("/stop", "sess-persist"))

    assert reply == "Stopped ct_channel"
    assert coding.stopped == ["ct_channel"]
    assert workflow.calls == []


async def test_channel_stop_does_not_call_execute_workflow(monkeypatch):
    store = InMemoryChannelCodingBindStore()
    coding = FakeCoding()
    gateway, workflow, _ = _gateway(monkeypatch, binds=store, coding=coding)
    await gateway.dispatch(_message("/code do it", "sess-stop"))

    reply = await gateway.dispatch(_message("/stop", "sess-stop"))

    assert reply == "Stopped ct_channel"
    assert workflow.calls == []
