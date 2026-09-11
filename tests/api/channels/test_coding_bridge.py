from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.api.channels.coding_bridge import RuntimeChannelCoding

pytestmark = pytest.mark.no_db


async def test_stop_task_uses_run_service_stop(monkeypatch) -> None:
    calls: list[dict] = []

    async def stop(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "neos.coding.runtime.coding_run_service",
        SimpleNamespace(stop=stop),
    )

    await RuntimeChannelCoding().stop_task(task_id="ct_1", owner_id="u_owner")

    assert calls == [{"task_id": "ct_1", "owner_id": "u_owner"}]
