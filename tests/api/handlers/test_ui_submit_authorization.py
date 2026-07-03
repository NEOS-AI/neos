import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.engine.result import IteratorResult, SimpleResultMetaData

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers import ui_submit_handlers
from neos.database.connection import db_manager, get_db


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

    class FakeSession:
        closed = False

        async def execute(self, statement):
            statements.append(statement)
            return IteratorResult(
                SimpleResultMetaData(["frame"]),
                iter([(owned_frame,)]),
            )

        async def close(self):
            self.closed = True

    session = FakeSession()
    monkeypatch.setattr(
        db_manager,
        "get_session",
        AsyncMock(return_value=session),
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
    assert session.closed is True


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

    get_session = AsyncMock(
        side_effect=AssertionError("frame state must not be mutated")
    )
    event_generator = Mock()
    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        fake_get_owned_frame,
    )
    monkeypatch.setattr(
        db_manager,
        "get_session",
        get_session,
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
    get_session.assert_not_awaited()
    event_generator.assert_not_called()


@pytest.mark.asyncio
async def test_ui_frame_atomic_update_is_scoped_to_authenticated_user(monkeypatch):
    statements = []
    frame_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    returned_conversation_id = uuid.UUID(
        "00000000-0000-0000-0000-000000000003"
    )
    update_result = IteratorResult(
        SimpleResultMetaData(
            [
                "frame_id",
                "session_id",
                "original_query",
                "conversation_id",
            ]
        ),
        iter(
            [
                (
                    frame_id,
                    "owned-session",
                    "fresh query",
                    returned_conversation_id,
                )
            ]
        ),
    )

    class FakeSession:
        committed = False
        closed = False

        async def execute(self, statement):
            statements.append(statement)
            return update_result

        async def commit(self):
            assert update_result.closed is True
            self.committed = True

        async def close(self):
            self.closed = True

    async def fake_get_owned_frame(frame_id, user_id):
        return SimpleNamespace(
            session_id="owned-session",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(minutes=5),
            original_query="stale query",
            conversation_id=uuid.UUID(
                "00000000-0000-0000-0000-000000000099"
            ),
        )

    async def events():
        yield "data: [DONE]\n\n"

    event_generator = Mock(return_value=events())
    session = FakeSession()

    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        fake_get_owned_frame,
    )
    monkeypatch.setattr(
        db_manager,
        "get_session",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        ui_submit_handlers,
        "_event_generator",
        event_generator,
    )

    await ui_submit_handlers.submit_ui_frame(
        SimpleNamespace(
            frame_id=str(frame_id),
            session_id="owned-session",
            values={"approved": True},
        ),
        current_user=SimpleNamespace(user_id="user-a"),
    )

    assert len(statements) == 1
    compiled = statements[0].compile()
    sql = str(compiled)
    assert "ui_frame_sessions.frame_id =" in sql
    assert "ui_frame_sessions.user_id =" in sql
    assert "ui_frame_sessions.session_id =" in sql
    assert "ui_frame_sessions.submitted_at IS NULL" in sql
    assert frame_id in compiled.params.values()
    assert "user-a" in compiled.params.values()
    assert "owned-session" in compiled.params.values()
    assert session.committed is True
    assert session.closed is True
    event_generator.assert_called_once_with(
        {
            "user_id": "user-a",
            "session_id": "owned-session",
            "query": "fresh query",
            "ui_submission": {"approved": True},
            "needs_ui": False,
            "conversation_id": str(returned_conversation_id),
        },
        "owned-session",
        "user-a",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("latest_frame", "expected_status", "expected_detail"),
    [
        (None, 404, "Resource not found"),
        (None, 404, "Resource not found"),
        (
            SimpleNamespace(
                session_id="changed-session",
                submitted_at=None,
            ),
            404,
            "Resource not found",
        ),
        (
            SimpleNamespace(
                session_id="owned-session",
                submitted_at=datetime(2026, 1, 1),
            ),
            409,
            "이미 제출된 UIFrame입니다.",
        ),
    ],
    ids=["missing", "owner-changed", "session-changed", "already-submitted"],
)
async def test_zero_row_update_rechecks_owned_state_before_classification(
    monkeypatch,
    latest_frame,
    expected_status,
    expected_detail,
):
    frame_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    initial_frame = SimpleNamespace(
        session_id="owned-session",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(minutes=5),
        original_query="stale query",
        conversation_id=None,
        submitted_at=None,
    )
    select_statements = []
    update_statements = []

    class SelectSession:
        def __init__(self, frame):
            self.frame = frame
            self.closed = False

        async def execute(self, statement):
            select_statements.append(statement)
            rows = [] if self.frame is None else [(self.frame,)]
            return IteratorResult(
                SimpleResultMetaData(["frame"]),
                iter(rows),
            )

        async def close(self):
            self.closed = True

    class UpdateSession:
        committed = False
        closed = False

        async def execute(self, statement):
            update_statements.append(statement)
            return IteratorResult(
                SimpleResultMetaData(
                    [
                        "frame_id",
                        "session_id",
                        "original_query",
                        "conversation_id",
                    ]
                ),
                iter([]),
            )

        async def commit(self):
            self.committed = True

        async def close(self):
            self.closed = True

    initial_session = SelectSession(initial_frame)
    update_session = UpdateSession()
    latest_session = SelectSession(latest_frame)
    get_session = AsyncMock(
        side_effect=[initial_session, update_session, latest_session]
    )
    event_generator = Mock()
    execute_workflow = AsyncMock()
    monkeypatch.setattr(db_manager, "get_session", get_session)
    monkeypatch.setattr(
        ui_submit_handlers,
        "_event_generator",
        event_generator,
    )
    monkeypatch.setattr(
        ui_submit_handlers.multi_agent_workflow,
        "execute_workflow",
        execute_workflow,
    )

    with pytest.raises(HTTPException) as exc:
        await ui_submit_handlers.submit_ui_frame(
            SimpleNamespace(
                frame_id=str(frame_id),
                session_id="owned-session",
                values={"approved": True},
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == expected_status
    assert exc.value.detail == expected_detail
    assert get_session.await_count == 3
    assert len(select_statements) == 2
    for statement in select_statements:
        compiled = statement.compile()
        assert "ui_frame_sessions.frame_id =" in str(compiled)
        assert "ui_frame_sessions.user_id =" in str(compiled)
        assert frame_id in compiled.params.values()
        assert "user-a" in compiled.params.values()
    assert len(update_statements) == 1
    assert update_session.committed is False
    assert initial_session.closed is True
    assert update_session.closed is True
    assert latest_session.closed is True
    event_generator.assert_not_called()
    execute_workflow.assert_not_awaited()


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
    statements = []

    class SelectSession:
        closed = False

        async def execute(self, statement):
            statements.append(statement)
            return IteratorResult(
                SimpleResultMetaData(["frame"]),
                iter([]),
            )

        async def close(self):
            self.closed = True

    session = SelectSession()
    get_session = AsyncMock(return_value=session)
    event_generator = Mock()
    monkeypatch.setattr(
        db_manager,
        "get_session",
        get_session,
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
    get_session.assert_awaited_once_with()
    assert len(statements) == 1
    compiled = statements[0].compile()
    sql = str(compiled)
    assert "ui_frame_sessions.frame_id =" in sql
    assert "ui_frame_sessions.user_id =" in sql
    assert uuid.UUID(frame_id) in compiled.params.values()
    assert "user-a" in compiled.params.values()
    assert session.closed is True
    event_generator.assert_not_called()


def test_owner_ui_frame_submit_preserves_sse_contract_and_identity(monkeypatch):
    frame_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    persisted_conversation_id = uuid.UUID(
        "00000000-0000-0000-0000-000000000003"
    )
    persisted_frame = SimpleNamespace(
        session_id="owned-session",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(minutes=5),
        original_query="original query",
        conversation_id=persisted_conversation_id,
    )
    captured = {}
    statements = []
    update_result = IteratorResult(
        SimpleResultMetaData(
            [
                "frame_id",
                "session_id",
                "original_query",
                "conversation_id",
            ]
        ),
        iter(
            [
                (
                    frame_id,
                    "owned-session",
                    "original query",
                    persisted_conversation_id,
                )
            ]
        ),
    )

    class SelectSession:
        closed = False

        async def execute(self, statement):
            statements.append(statement)
            return IteratorResult(
                SimpleResultMetaData(["frame"]),
                iter([(persisted_frame,)]),
            )

        async def close(self):
            self.closed = True

    class UpdateSession:
        committed = False
        closed = False

        async def execute(self, statement):
            statements.append(statement)
            return update_result

        async def commit(self):
            assert update_result.closed is True
            self.committed = True

        async def close(self):
            self.closed = True

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

    select_session = SelectSession()
    update_session = UpdateSession()
    get_session = AsyncMock(side_effect=[select_session, update_session])
    monkeypatch.setattr(
        db_manager,
        "get_session",
        get_session,
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
                "frame_id": str(frame_id),
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
    assert get_session.await_count == 2
    assert len(statements) == 2
    assert select_session.closed is True
    assert update_session.committed is True
    assert update_session.closed is True
