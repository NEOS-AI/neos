from types import SimpleNamespace

import pytest

from neos.api.channels.coding_bridge import RuntimeChannelCoding
from neos.coding.domain.approvals import ApprovalStatus

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_channel_cannot_approve_ask_user_without_answers(monkeypatch) -> None:
    pending = SimpleNamespace(
        approval_id="ca_9",
        tool_name="ask_user.v1",
        status=ApprovalStatus.PENDING,
    )

    class Snapshot:
        async def get_owned(self, task_id, owner_id):
            return SimpleNamespace(approvals=(pending,))

    import neos.coding.runtime as runtime

    monkeypatch.setattr(runtime, "coding_snapshot_service", Snapshot())
    reply = await RuntimeChannelCoding().decide(
        task_id="ct_1", owner_id="u1", approve=True, approval_id="ca_9"
    )
    assert "Code UI" in reply
