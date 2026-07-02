import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers import ui_submit_handlers
from neos.database.connection import get_db


def _app(current_user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(ui_submit_handlers.router, prefix="/api/v1")

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.mark.asyncio
async def test_ui_frame_lookup_receives_authenticated_user(monkeypatch):
    captured = {}

    async def fake_get_owned_frame(frame_id, user_id):
        captured.update(frame_id=frame_id, user_id=user_id)
        return None

    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        fake_get_owned_frame,
    )
    body = SimpleNamespace(
        frame_id="00000000-0000-0000-0000-000000000001",
        session_id="s1",
        values={},
    )

    with pytest.raises(HTTPException) as exc:
        await ui_submit_handlers.submit_ui_frame(
            body,
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 404
    assert captured["user_id"] == "user-a"


@pytest.mark.asyncio
async def test_owned_ui_frame_lookup_scopes_select_to_frame_and_user(monkeypatch):
    statements = []
    owned_frame = object()

    class FakeResult:
        def scalar_one_or_none(self):
            return owned_frame

    class FakeSession:
        async def execute(self, statement):
            statements.append(statement)
            return FakeResult()

    @asynccontextmanager
    async def fake_get_db_session():
        yield FakeSession()

    monkeypatch.setattr(
        ui_submit_handlers,
        "get_db_session",
        fake_get_db_session,
    )
    frame_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    result = await ui_submit_handlers._get_owned_frame_session(
        frame_id,
        "user-a",
    )

    assert result is owned_frame
    assert len(statements) == 1
    compiled = statements[0].compile()
    sql = str(compiled)
    assert "ui_frame_sessions.frame_id =" in sql
    assert "ui_frame_sessions.user_id =" in sql
    assert frame_id in compiled.params.values()
    assert "user-a" in compiled.params.values()


@pytest.mark.asyncio
async def test_ui_frame_session_mismatch_is_hidden_before_side_effects(monkeypatch):
    frame_session = SimpleNamespace(
        session_id="owned-session",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(minutes=5),
        original_query="original query",
        conversation_id=None,
    )

    async def fake_get_owned_frame(frame_id, user_id):
        return frame_session

    def fail_get_db_session():
        raise AssertionError("frame state must not be mutated")

    event_generator = Mock()
    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        fake_get_owned_frame,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "get_db_session",
        fail_get_db_session,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "_event_generator",
        event_generator,
    )

    with pytest.raises(HTTPException) as exc:
        await ui_submit_handlers.submit_ui_frame(
            SimpleNamespace(
                frame_id="00000000-0000-0000-0000-000000000001",
                session_id="other-session",
                values={},
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    event_generator.assert_not_called()


@pytest.mark.asyncio
async def test_ui_frame_atomic_update_is_scoped_to_authenticated_user(monkeypatch):
    statements = []

    class FakeSession:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)

        async def commit(self):
            return None

    @asynccontextmanager
    async def fake_get_db_session():
        yield FakeSession()

    async def fake_get_owned_frame(frame_id, user_id):
        return SimpleNamespace(
            session_id="owned-session",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(minutes=5),
            original_query="original query",
            conversation_id=None,
        )

    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        fake_get_owned_frame,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "get_db_session",
        fake_get_db_session,
    )

    await ui_submit_handlers.submit_ui_frame(
        SimpleNamespace(
            frame_id="00000000-0000-0000-0000-000000000001",
            session_id="owned-session",
            values={},
        ),
        current_user=SimpleNamespace(user_id="user-a"),
    )

    assert len(statements) == 1
    compiled = statements[0].compile()
    assert "ui_frame_sessions.user_id =" in str(compiled)
    assert "user-a" in compiled.params.values()


def test_ui_frame_submit_requires_authentication_before_frame_lookup(monkeypatch):
    lookup = AsyncMock()
    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        lookup,
    )

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/ui/submit",
            json={
                "frame_id": "00000000-0000-0000-0000-000000000001",
                "session_id": "s1",
                "values": {},
            },
        )

    assert response.status_code == 401
    lookup.assert_not_awaited()


@pytest.mark.parametrize(
    "frame_id",
    [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ],
    ids=["missing", "foreign"],
)
def test_missing_and_foreign_ui_frames_share_404_before_side_effects(
    monkeypatch,
    frame_id,
):
    lookup = AsyncMock(return_value=None)
    update_session = Mock()
    event_generator = Mock()
    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        lookup,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "get_db_session",
        update_session,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "_event_generator",
        event_generator,
    )

    with TestClient(_app(SimpleNamespace(user_id="user-a"))) as client:
        response = client.post(
            "/api/v1/ui/submit",
            json={
                "frame_id": frame_id,
                "session_id": "victim-session",
                "values": {"approved": True},
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    assert lookup.await_args.args == (uuid.UUID(frame_id), "user-a")
    update_session.assert_not_called()
    event_generator.assert_not_called()


def test_owner_ui_frame_submit_preserves_sse_contract_and_identity(monkeypatch):
    persisted_conversation_id = uuid.UUID(
        "00000000-0000-0000-0000-000000000003"
    )
    lookup = AsyncMock(
        return_value=SimpleNamespace(
            session_id="owned-session",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(minutes=5),
            original_query="original query",
            conversation_id=persisted_conversation_id,
        )
    )
    captured = {}

    class FakeSession:
        async def execute(self, statement):
            return SimpleNamespace(rowcount=1)

        async def commit(self):
            return None

    @asynccontextmanager
    async def fake_get_db_session():
        yield FakeSession()

    async def events():
        yield 'data: {"event":"completed","data":{"response":"ok"}}\n\n'
        yield "data: [DONE]\n\n"

    def fake_event_generator(workflow_input, session_id, user_id):
        captured.update(
            workflow_input=workflow_input,
            session_id=session_id,
            user_id=user_id,
        )
        return events()

    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        lookup,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "get_db_session",
        fake_get_db_session,
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "_event_generator",
        fake_event_generator,
    )

    with TestClient(_app(SimpleNamespace(user_id="user-a"))) as client:
        response = client.post(
            "/api/v1/ui/submit",
            json={
                "frame_id": "00000000-0000-0000-0000-000000000001",
                "session_id": "owned-session",
                "conversation_id": "00000000-0000-0000-0000-000000000099",
                "user_id": "victim-user",
                "values": {"approved": True},
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text == (
        'data: {"event":"completed","data":{"response":"ok"}}\n\n'
        "data: [DONE]\n\n"
    )
    assert captured == {
        "workflow_input": {
            "user_id": "user-a",
            "session_id": "owned-session",
            "query": "original query",
            "ui_submission": {"approved": True},
            "needs_ui": False,
            "conversation_id": str(persisted_conversation_id),
        },
        "session_id": "owned-session",
        "user_id": "user-a",
    }
