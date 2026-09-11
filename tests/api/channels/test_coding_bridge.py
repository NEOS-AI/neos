from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.api.channels.coding_bridge import RuntimeChannelCoding
from neos.coding.domain.phases import SteeringMode

pytestmark = pytest.mark.no_db


async def test_stop_task_uses_durable_interrupt_steer(monkeypatch) -> None:
    calls: list[dict] = []

    async def steer(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(steering_id="cs_1", mode=kwargs["mode"])

    monkeypatch.setattr(
        "neos.coding.runtime.coding_run_service",
        SimpleNamespace(steer=steer, stop=None),
    )

    await RuntimeChannelCoding().stop_task(task_id="ct_1", owner_id="u_owner")

    assert len(calls) == 1
    assert calls[0]["task_id"] == "ct_1"
    assert calls[0]["owner_id"] == "u_owner"
    assert calls[0]["instruction"] == "stop"
    assert calls[0]["mode"] is SteeringMode.INTERRUPT_NOW
