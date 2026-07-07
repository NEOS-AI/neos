from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_scheduled_tasks_imports_production_session_context_manager():
    source = (
        __import__("pathlib").Path("neos/api/handlers/scheduled_tasks_handlers.py")
        .read_text()
    )

    assert "from neos.database.connection import get_session_ctx" in source
    assert "get_async_session" not in source


@pytest.mark.asyncio
async def test_list_scheduled_tasks_closes_production_session_context(monkeypatch):
    from neos.api.handlers import scheduled_tasks_handlers

    entered = False
    exited = False
    scalar_result = SimpleNamespace(all=lambda: [])
    session = SimpleNamespace(scalars=AsyncMock(return_value=scalar_result))

    @asynccontextmanager
    async def fake_session_context():
        nonlocal entered, exited
        entered = True
        try:
            yield session
        finally:
            exited = True

    monkeypatch.setattr(
        scheduled_tasks_handlers,
        "get_session_ctx",
        fake_session_context,
    )

    result = await scheduled_tasks_handlers.list_scheduled_tasks(
        active_only=False,
        current_user=SimpleNamespace(user_id="owner"),
    )

    assert result == []
    assert entered is True
    assert exited is True
