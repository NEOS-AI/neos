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


def _app(current_user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(approval_handlers.router)

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _graph_with_pending(*pending):
    return SimpleNamespace(
        aget_state=AsyncMock(
            return_value=SimpleNamespace(
                values={"pending_approvals": list(pending)},
            )
        ),
        aupdate_state=AsyncMock(),
        checkpointer=Mock(),
    )


def _configure_workflow(monkeypatch, graph):
    monkeypatch.setattr(
        approval_handlers.multi_agent_workflow,
        "_graph_initialized",
        True,
    )
    monkeypatch.setattr(
        approval_handlers.multi_agent_workflow,
        "_graph_uses_checkpointer",
        True,
    )
    monkeypatch.setattr(approval_handlers.multi_agent_workflow, "graph", graph)


def _close_created_task(coro, *, name):
    coro.close()


class _AsyncioProxy:
    """`approval_handlers` 안에서만 보이는 asyncio 대역.

    🔴 **`monkeypatch.setattr(approval_handlers.asyncio, "create_task", ...)` 로
    쓰면 안 된다.** `approval_handlers.asyncio` 는 이 모듈의 지역 별칭이 아니라
    **전역 `asyncio` 모듈 객체 그 자체**다. 그 속성을 바꾸면 프로세스 전체의
    `asyncio.create_task` 가 Mock 이 된다.

    그러면 같은 테스트 안의 `TestClient(...)` 가 매달린다: starlette 이 앱
    lifespan 을 돌리려고 띄우는 anyio blocking portal 이 그 Mock 을 받아
    코루틴이 닫힌 채 Task 가 만들어지지 않고, 포털 스레드가 영원히 준비되지
    않아 `__enter__` 의 정리가 `join()` 에서 멈춘다. **실패가 아니라 멈춤이라
    pytest 가 세지도 않는다** -- 전체 스위트가 시드에 따라 10시간씩 매달렸다
    (로드맵 §7.4).

    순서 의존이었던 이유: 앞선 테스트가 패치 없이 `TestClient` 를 한 번 띄워
    두면 그 경로가 예열돼 통과했다. 그래서 파일 전체로는 초록이고 **그 테스트만
    따로 돌리면 멈췄다** -- 단독 실행이 오히려 더 정직한 신호였다.

    가로챌 곳은 공유 모듈이 아니라 **모듈이 들고 있는 이름**이다.
    """

    def __init__(self, create_task):
        self.create_task = create_task

    def __getattr__(self, name):
        # 인스턴스 속성 조회가 실패했을 때만 온다 -- `create_task` 는 여기 안 온다.
        return getattr(asyncio, name)


@pytest.mark.asyncio
async def test_pending_approval_lookup_is_scoped_to_user(monkeypatch):
    fetch_one = AsyncMock(return_value=None)
    monkeypatch.setattr(
        approval_handlers,
        "db_manager",
        SimpleNamespace(fetch_one=fetch_one),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc:
        await approval_handlers._require_pending_approval_owner(
            session_id="s1",
            request_id="r1",
            user_id="user-a",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    assert "user_id = $3" in fetch_one.await_args.args[0]
    assert fetch_one.await_args.args[1:] == ("s1", "r1", "user-a")


@pytest.mark.asyncio
async def test_resume_stream_hides_other_users_session(monkeypatch):
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: SimpleNamespace(user_id="user-b"),
    )

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.stream_resume_result(
            "s1",
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"


def test_approval_response_requires_authentication_before_store_or_graph(monkeypatch):
    fetch_one = AsyncMock()
    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "mission_runtime"},
    )
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    _configure_workflow(monkeypatch, graph)

    with TestClient(_app()) as client:
        response = client.post(
            "/approval/respond",
            json={
                "session_id": "s1",
                "request_id": "r1",
                "decision": "approved",
            },
        )

    assert response.status_code == 401
    fetch_one.assert_not_awaited()
    graph.aget_state.assert_not_awaited()
    graph.aupdate_state.assert_not_awaited()


def test_approval_response_hides_other_users_approval_before_graph(monkeypatch):
    fetch_one = AsyncMock(return_value=None)
    execute = AsyncMock()
    graph = _graph_with_pending(
        {"request_id": "victim-r", "skill_name": "mission_runtime"},
    )
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    _configure_workflow(monkeypatch, graph)

    with TestClient(
        _app(SimpleNamespace(user_id="user-a", is_active=True))
    ) as client:
        response = client.post(
            "/approval/respond",
            json={
                "session_id": "victim-s",
                "request_id": "victim-r",
                "decision": "approved",
                "user_id": "victim",
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    assert fetch_one.await_args.args[1:] == ("victim-s", "victim-r", "user-a")
    graph.aget_state.assert_not_awaited()
    graph.aupdate_state.assert_not_awaited()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_missing_approval_is_hidden_before_workflow_availability_check(
    monkeypatch,
):
    fetch_one = AsyncMock(return_value=None)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(
        approval_handlers.multi_agent_workflow,
        "_graph_initialized",
        False,
    )
    monkeypatch.setattr(
        approval_handlers.multi_agent_workflow,
        "_graph_uses_checkpointer",
        False,
    )

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(
            approval_handlers.ApprovalResponse(
                session_id="missing-s",
                request_id="missing-r",
                decision="approved",
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    fetch_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_approval_response_hides_foreign_stream_before_state_mutation(
    monkeypatch,
):
    fetch_one = AsyncMock(
        return_value=("r1", "s1", "user-a", "mission_runtime", False),
    )
    execute = AsyncMock()
    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "mission_runtime"},
    )
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: SimpleNamespace(user_id="user-b"),
    )
    _configure_workflow(monkeypatch, graph)

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(
            approval_handlers.ApprovalResponse(
                session_id="s1",
                request_id="r1",
                decision="approved",
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    graph.aget_state.assert_not_awaited()
    graph.aupdate_state.assert_not_awaited()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_graph_skill_must_match_persisted_approval_without_allowlist(
    monkeypatch,
):
    fetch_one = AsyncMock(
        return_value=("r1", "s1", "user-a", "persisted-skill", False),
    )
    execute = AsyncMock()
    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "different-skill"},
    )
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: SimpleNamespace(user_id="user-a"),
    )
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    _configure_workflow(monkeypatch, graph)

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(
            approval_handlers.ApprovalResponse(
                session_id="s1",
                request_id="r1",
                decision="approved",
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 400
    graph.aupdate_state.assert_not_awaited()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_allowlist_skill_must_match_persisted_approval(monkeypatch):
    fetch_one = AsyncMock(
        return_value=("r1", "s1", "user-a", "persisted-skill", False),
    )
    execute = AsyncMock()
    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "forged-skill"},
    )
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: None,
    )
    _configure_workflow(monkeypatch, graph)

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(
            approval_handlers.ApprovalResponse(
                session_id="s1",
                request_id="r1",
                decision="approved",
                add_to_allowlist=True,
                skill_name="forged-skill",
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 400
    graph.aupdate_state.assert_not_awaited()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_approval_response_creates_owned_stream_before_state_mutation(
    monkeypatch,
):
    fetch_one = AsyncMock(
        return_value=("r1", "s1", "user-a", "mission_runtime", False),
    )
    execute = AsyncMock()
    create_session = Mock(return_value=SimpleNamespace(user_id="user-a"))

    async def update_state(*, config, values):
        create_session.assert_called_once_with("s1", "user-a")

    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "mission_runtime"},
    )
    graph.aupdate_state = AsyncMock(side_effect=update_state)
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: None,
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "create_session",
        create_session,
    )
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    _configure_workflow(monkeypatch, graph)

    result = await approval_handlers.respond_to_approval(
        approval_handlers.ApprovalResponse(
            session_id="s1",
            request_id="r1",
            decision="approved",
        ),
        current_user=SimpleNamespace(user_id="user-a"),
    )

    assert result.model_dump() == {
        "status": "resumed",
        "session_id": "s1",
        "decision": "approved",
    }
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_created_stream_session_owner_is_verified_before_state_mutation(
    monkeypatch,
):
    fetch_one = AsyncMock(
        return_value=("r1", "s1", "user-a", "mission_runtime", False),
    )
    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "mission_runtime"},
    )
    execute = AsyncMock()
    create_session = Mock(return_value=SimpleNamespace(user_id="user-b"))
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: None,
    )
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "create_session",
        create_session,
    )
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    _configure_workflow(monkeypatch, graph)

    with pytest.raises(HTTPException) as exc:
        await approval_handlers.respond_to_approval(
            approval_handlers.ApprovalResponse(
                session_id="s1",
                request_id="r1",
                decision="approved",
            ),
            current_user=SimpleNamespace(user_id="user-a"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    graph.aupdate_state.assert_not_awaited()
    create_task.assert_not_called()


def test_approval_response_owner_preserves_http_response_schema(monkeypatch):
    fetch_one = AsyncMock(
        return_value=("r1", "s1", "user-a", "mission_runtime", False),
    )
    execute = AsyncMock()
    graph = _graph_with_pending(
        {"request_id": "r1", "skill_name": "mission_runtime"},
    )
    create_task = Mock(side_effect=_close_created_task)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: SimpleNamespace(user_id="user-a"),
    )
    monkeypatch.setattr(
        approval_handlers, "asyncio", _AsyncioProxy(create_task)
    )
    _configure_workflow(monkeypatch, graph)

    with TestClient(
        _app(SimpleNamespace(user_id="user-a", is_active=True))
    ) as client:
        response = client.post(
            "/approval/respond",
            json={
                "session_id": "s1",
                "request_id": "r1",
                "decision": "approved",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "resumed",
        "session_id": "s1",
        "decision": "approved",
    }
    graph.aupdate_state.assert_awaited_once_with(
        config={"configurable": {"thread_id": "s1"}},
        values={"approval_decision": "approved"},
    )
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_mark_approval_resolved_is_scoped_to_user(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(approval_handlers.db_manager, "execute", execute)

    await approval_handlers._mark_approval_resolved("r1", "user-a")

    assert "user_id = $2" in execute.await_args.args[0]
    assert execute.await_args.args[1:] == ("r1", "user-a")


@pytest.mark.parametrize("session", [None, SimpleNamespace(user_id="user-b")])
def test_approval_stream_hides_missing_and_non_owner_as_json_404(
    monkeypatch,
    session,
):
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: session,
    )

    with TestClient(
        _app(SimpleNamespace(user_id="user-a", is_active=True))
    ) as client:
        response = client.get("/approval/stream/s1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    assert response.headers["content-type"].startswith("application/json")


def test_approval_stream_owner_preserves_sse_event_contract(monkeypatch):
    event = SimpleNamespace(
        event="completed",
        to_sse_format=lambda: (
            "id: 1\nevent: completed\ndata: {\"response\": \"done\"}\n\n"
        ),
    )
    session = SimpleNamespace(
        user_id="user-a",
        queue=SimpleNamespace(get=AsyncMock(return_value=event)),
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
    assert response.text == (
        "id: 1\nevent: completed\ndata: {\"response\": \"done\"}\n\n"
    )
