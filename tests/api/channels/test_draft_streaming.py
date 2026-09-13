from __future__ import annotations

import pytest

from tests.api.channels.conftest import install_channel_settings
from tests.api.channels.test_gateway_router import (
    FakeCoding,
    FakeWorkflow,
    _gateway,
    _message,
)

pytestmark = pytest.mark.no_db


class FakeDraftAdapter:
    channel_type = "slack"

    def __init__(self) -> None:
        self.drafts: list[tuple[str, str, str | None]] = []

    async def send_draft(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        self.drafts.append((channel_id, content, thread_id))

    async def send_response(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        del channel_id, content, thread_id


def _register(gateway, adapter: FakeDraftAdapter) -> FakeDraftAdapter:
    gateway.register_adapter(adapter)
    return adapter


async def test_draft_streaming_off_does_not_send_drafts(monkeypatch) -> None:
    gateway, _workflow, _coding = _gateway(monkeypatch)
    adapter = _register(gateway, FakeDraftAdapter())

    await gateway.dispatch(_message("hello <@U_BOT>"))
    await gateway.dispatch(_message("/code fix it"))

    assert adapter.drafts == []


async def test_draft_streaming_sends_workflow_and_coding_start_acks(
    monkeypatch,
) -> None:
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
        draft_streaming=True,
    )
    from neos.api.channels.gateway import ChannelGateway

    workflow = FakeWorkflow()
    coding = FakeCoding()
    gateway = ChannelGateway(workflow, coding=coding)
    adapter = _register(gateway, FakeDraftAdapter())
    chat = _message("hello <@U_BOT>")
    chat.metadata["thread_id"] = "99"
    code = _message("/code fix it", "v2:slack:T:C:code")
    code.metadata["thread_id"] = "100"

    await gateway.dispatch(chat)
    await gateway.dispatch(code)

    assert adapter.drafts == [
        ("C", "Working...", "99"),
        ("C", "Starting coding task...", "100"),
    ]
    assert workflow.calls
    assert coding.started


async def test_draft_streaming_off_by_default_even_if_adapter_registered(
    monkeypatch,
) -> None:
    from neos.config.schema import ChannelConfig

    assert ChannelConfig().draft_streaming is False
    gateway, _workflow, _coding = _gateway(monkeypatch)
    adapter = _register(gateway, FakeDraftAdapter())
    await gateway.dispatch(_message("hello <@U_BOT>"))
    assert adapter.drafts == []
