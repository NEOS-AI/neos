"""approval resume 스트림의 타임아웃 경로가 정상 경로와 같은 SSE 포맷을
내보내는지 고정한다 (감사 finding #3).

`asyncio.wait_for(session.queue.get(), timeout=60.0)`가 실제로 60초를
기다리면 pytest의 30초 타임아웃에 걸리므로, `session.queue.get`이
`asyncio.TimeoutError`를 즉시 던지도록 만든다 -- `wait_for`는 감싼
awaitable이 스스로 던진 예외를 그대로 전파하며 벽시계 타임아웃까지
기다리지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers import approval_handlers
from neos.database.connection import get_db


def _app(current_user) -> FastAPI:
    app = FastAPI()
    app.include_router(approval_handlers.router)

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _data_lines(body: str) -> list[str]:
    return [line for line in body.split("\n") if line.startswith("data:")]


def test_timeout_path_emits_event_line_like_the_normal_path(monkeypatch):
    """타임아웃 경로도 `event: error` 줄을 내보내야 한다.

    지금은 손으로 만든 `data:` 한 줄뿐이라 `event:` 줄이 없다 -- FE가
    이벤트 종류를 오직 `event:` 줄로만 판별하면 이 payload는 유실된다.
    """
    session = SimpleNamespace(
        user_id="user-a",
        last_event_id=0,
        queue=SimpleNamespace(get=AsyncMock(side_effect=asyncio.TimeoutError)),
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: session,
    )

    with TestClient(
        _app(SimpleNamespace(user_id="user-a", is_active=True))
    ) as client:
        response = client.get("/approval/stream/s1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    lines = response.text.split("\n")
    assert "event: error" in lines, (
        f"expected an 'event: error' line, got: {response.text!r}"
    )


def test_timeout_path_payload_keeps_event_and_message_keys(monkeypatch):
    """payload는 기존 키(`event`, `message`)를 유지해야 한다."""
    session = SimpleNamespace(
        user_id="user-a",
        last_event_id=0,
        queue=SimpleNamespace(get=AsyncMock(side_effect=asyncio.TimeoutError)),
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: session,
    )

    with TestClient(
        _app(SimpleNamespace(user_id="user-a", is_active=True))
    ) as client:
        response = client.get("/approval/stream/s1")

    data_lines = _data_lines(response.text)
    assert data_lines, f"no data: line found in {response.text!r}"
    payload = json.loads(data_lines[0][len("data:"):].strip())
    assert payload["event"] == "error"
    assert payload["message"] == "워크플로우 응답 대기 타임아웃"


def test_timeout_path_uses_the_shared_formatter(monkeypatch):
    """타임아웃 경로도 `StreamEvent.to_sse_format()`을 태워야 한다.

    포맷터가 하나여야 정상 경로와 타임아웃 경로가 다시 갈라지지 않는다.
    `to_sse_format`을 스파이로 바꿔서 실제로 호출되는지 확인한다.
    """
    from neos.workflow.stream_manager import StreamEvent

    calls: list[StreamEvent] = []
    original_to_sse_format = StreamEvent.to_sse_format

    def spy(self: StreamEvent) -> str:
        calls.append(self)
        return original_to_sse_format(self)

    monkeypatch.setattr(StreamEvent, "to_sse_format", spy)

    session = SimpleNamespace(
        user_id="user-a",
        last_event_id=0,
        queue=SimpleNamespace(get=AsyncMock(side_effect=asyncio.TimeoutError)),
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: session,
    )

    with TestClient(
        _app(SimpleNamespace(user_id="user-a", is_active=True))
    ) as client:
        response = client.get("/approval/stream/s1")

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0].event == "error"
