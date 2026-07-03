from unittest.mock import AsyncMock

import pytest

from neos.database.connection import db_manager
from neos.workflow.processors.ui_frame_generator import UIFrameGenerator


@pytest.mark.asyncio
async def test_save_frame_session_uses_production_context_manager_contract(
    monkeypatch,
):
    added = []

    class FakeSession:
        committed = False
        closed = False

        def add(self, value):
            added.append(value)

        async def commit(self):
            self.committed = True

        async def close(self):
            self.closed = True

    session = FakeSession()
    monkeypatch.setattr(
        db_manager,
        "get_session",
        AsyncMock(return_value=session),
    )

    saved = await UIFrameGenerator()._save_frame_session(
        frame_id="00000000-0000-0000-0000-000000000001",
        session_id="owned-session",
        conversation_id="00000000-0000-0000-0000-000000000002",
        original_query="original query",
        frame_data={"intent": "test"},
        user_id="user-a",
    )

    assert saved is True
    assert len(added) == 1
    assert added[0].session_id == "owned-session"
    assert added[0].user_id == "user-a"
    assert session.committed is True
    assert session.closed is True
