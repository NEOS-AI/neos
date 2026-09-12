from __future__ import annotations

import pytest

from neos.api.channels.gateway import ChannelGateway
from tests.api.channels.test_draft_streaming import FakeDraftAdapter
from tests.api.channels.test_gateway_router import FakeCoding, FakeWorkflow

pytestmark = pytest.mark.no_db


class RecordingAdapter(FakeDraftAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str, str | None]] = []

    async def send_response(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        self.sent.append((channel_id, content, thread_id))


async def test_send_to_channel_uses_registered_adapter() -> None:
    gateway = ChannelGateway(FakeWorkflow(), coding=FakeCoding())
    adapter = RecordingAdapter()
    gateway.register_adapter(adapter)

    await gateway.send_to_channel("slack", "C123", "nightly report")

    assert adapter.sent == [("C123", "nightly report", None)]


async def test_scheduler_posts_result_via_gateway_adapter() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "neos"
        / "tasks"
        / "scheduled_task_runner.py"
    ).read_text(encoding="utf-8")
    assert "ChannelGateway.get_instance()" in source
    assert "gateway.send_to_channel" in source

    gateway = ChannelGateway(FakeWorkflow(), coding=FakeCoding())
    adapter = RecordingAdapter()
    gateway.register_adapter(adapter)
    ChannelGateway.set_instance(gateway)
    try:
        instance = ChannelGateway.get_instance()
        await instance.send_to_channel("slack", "C-bound", "scheduled result")
    finally:
        ChannelGateway.set_instance(None)

    assert adapter.sent == [("C-bound", "scheduled result", None)]
