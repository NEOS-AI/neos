"""웹 승인 응답의 네이티브 가지 -- 권한 검사 순서와 응답 모양 (spec 2026-10-13 §4.5).

`test_approval_authorization.py` 의 LangGraph 그래프 대역 대신 메모리 작업 행으로 같은 계약을
시험한다: 남의 스트림은 상태를 바꾸기(결정 = 작업 행 claim) 전에 404 로 숨고, 새로 만든
스트림의 소유자도 바꾸기 전에 확인되며, 응답 스키마는 같다. 거절 사유는 LangGraph 가지의
문구로 나간다 -- 내부 사유 코드가 새지 않는다.
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers import approval_handlers
from neos.database.connection import get_db
from neos.workflow.runtime import select
from neos.workflow.runtime.approvals import Refusal, WorkflowApprovals
from neos.workflow.runtime.work import InMemoryWorkStore, WorkLifecycle

pytestmark = pytest.mark.no_db

_INVALID = "유효하지 않은 request_id입니다. 해당 세션의 pending approval이 아닙니다."


def _app(current_user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(approval_handlers.router)

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _close_created_task(coro, *, name):
    coro.close()


class _AsyncioProxy:
    """`approval_handlers` 가 쥔 `asyncio` 이름만 바꾼다 -- 전역 모듈을 패치하면 TestClient 가 멈춘다
    (`test_approval_authorization._AsyncioProxy` 참조)."""

    def __init__(self, create_task):
        self.create_task = create_task

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _native(monkeypatch, *, seeded: bool = True):
    """네이티브 런타임을 켜고 메모리 작업 저장소를 꽂는다. 돌려주는 `seed()` 가 세션 s1 에 r1 을
    기다리는 작업 행을 심는다(동기 TestClient 테스트가 자기 루프에서 부를 수 있게 코루틴 함수로 준다)."""
    monkeypatch.setattr(approval_handlers.multi_agent_workflow, "_graph_initialized", False)
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.workflow, "runtime", "native")
    lifecycle = WorkLifecycle(InMemoryWorkStore())
    monkeypatch.setattr(select, "_approvals", WorkflowApprovals(SimpleNamespace(), lifecycle))
    if not seeded:
        return lifecycle, None

    async def _seed() -> str:
        work_id = await lifecycle.start(
            "web", "workflow", user_id="user-a", session_id="s1",
            delivery={"kind": "sse", "conversation_id": "s1"},
        )
        await lifecycle.interrupt(
            work_id,
            {
                "next_node": "execution_approval",
                "request_ids": ["r1"],
                "pending": [{"request_id": "r1", "skill_name": "mission_runtime"}],
                "session_version": 1,
            },
        )
        return work_id

    return lifecycle, _seed


async def _seeded(monkeypatch) -> tuple[WorkLifecycle, str]:
    lifecycle, seed = _native(monkeypatch)
    return lifecycle, await seed()


def _owner_row(monkeypatch):
    fetch_one = AsyncMock(return_value=("r1", "s1", "user-a", "mission_runtime", False))
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", AsyncMock())
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(approval_handlers, "asyncio", _AsyncioProxy(create_task))
    return create_task


def _body(**overrides):
    return approval_handlers.ApprovalResponse(
        **{"session_id": "s1", "request_id": "r1", "decision": "approved", **overrides}
    )


@pytest.mark.asyncio
async def test_native_response_hides_foreign_stream_before_state_mutation(monkeypatch) -> None:
    lifecycle, work_id = await _seeded(monkeypatch)
    create_task = _owner_row(monkeypatch)
    monkeypatch.setattr(
        approval_handlers.stream_manager, "get_session", lambda _sid: SimpleNamespace(user_id="user-b")
    )

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(_body(), current_user=SimpleNamespace(user_id="user-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    assert (await lifecycle.store.get(work_id)).status == "waiting_approval"
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_native_response_hides_foreign_stream_before_the_pending_lookup(monkeypatch) -> None:
    """대기 행이 없어도 남의 스트림이면 400 이 아니라 404 다 -- LangGraph 가지와 같은 순서."""
    _native(monkeypatch, seeded=False)
    create_task = _owner_row(monkeypatch)
    monkeypatch.setattr(
        approval_handlers.stream_manager, "get_session", lambda _sid: SimpleNamespace(user_id="user-b")
    )
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(select._approvals, "pending_for_session", lookup)

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(_body(), current_user=SimpleNamespace(user_id="user-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    lookup.assert_not_awaited()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_native_created_stream_session_owner_is_verified_before_state_mutation(monkeypatch) -> None:
    lifecycle, work_id = await _seeded(monkeypatch)
    create_task = _owner_row(monkeypatch)
    monkeypatch.setattr(approval_handlers.stream_manager, "get_session", lambda _sid: None)
    monkeypatch.setattr(
        approval_handlers.stream_manager, "create_session", Mock(return_value=SimpleNamespace(user_id="user-b"))
    )

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(_body(), current_user=SimpleNamespace(user_id="user-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    assert (await lifecycle.store.get(work_id)).status == "waiting_approval"
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_native_response_creates_owned_stream_before_state_mutation(monkeypatch) -> None:
    lifecycle, work_id = await _seeded(monkeypatch)
    create_task = _owner_row(monkeypatch)
    create_session = Mock(return_value=SimpleNamespace(user_id="user-a"))
    monkeypatch.setattr(approval_handlers.stream_manager, "get_session", lambda _sid: None)
    monkeypatch.setattr(approval_handlers.stream_manager, "create_session", create_session)
    real_claim = lifecycle.claim

    async def claim(*args, **kwargs):
        create_session.assert_called_once_with("s1", "user-a")
        return await real_claim(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "claim", claim)

    result = await approval_handlers.respond_to_approval(_body(), current_user=SimpleNamespace(user_id="user-a"))

    assert result.model_dump() == {"status": "resumed", "session_id": "s1", "decision": "approved"}
    assert (await lifecycle.store.get(work_id)).status == "running"
    create_task.assert_called_once()


def test_native_response_owner_preserves_http_response_schema(monkeypatch) -> None:
    lifecycle, seed = _native(monkeypatch)
    work_id = asyncio.run(seed())
    create_task = _owner_row(monkeypatch)
    monkeypatch.setattr(
        approval_handlers.stream_manager, "get_session", lambda _sid: SimpleNamespace(user_id="user-a")
    )

    with TestClient(_app(SimpleNamespace(user_id="user-a", is_active=True))) as client:
        response = client.post(
            "/approval/respond", json={"session_id": "s1", "request_id": "r1", "decision": "approved"}
        )

    assert response.status_code == 200
    assert response.json() == {"status": "resumed", "session_id": "s1", "decision": "approved"}
    assert asyncio.run(lifecycle.store.get(work_id)).status == "running"
    create_task.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "status_code", "detail"),
    [
        ("unknown_request", 400, _INVALID),
        ("expired", 400, _INVALID),
        ("conflict", 409, "이미 처리된 승인입니다."),
        ("not_owner", 404, "Resource not found"),
    ],
    ids=["unknown_request", "expired", "conflict", "not_owner"],
)
async def test_native_refusals_use_the_langgraph_messages(monkeypatch, reason, status_code, detail) -> None:
    await _seeded(monkeypatch)
    create_task = _owner_row(monkeypatch)
    monkeypatch.setattr(
        approval_handlers.stream_manager, "get_session", lambda _sid: SimpleNamespace(user_id="user-a")
    )
    monkeypatch.setattr(select._approvals, "decide", AsyncMock(return_value=Refusal(reason)))

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(_body(), current_user=SimpleNamespace(user_id="user-a"))

    assert (exc.value.status_code, exc.value.detail) == (status_code, detail)
    assert reason not in str(exc.value.detail)
    create_task.assert_not_called()
