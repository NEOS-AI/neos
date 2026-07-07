import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import (
    get_current_active_user,
    get_current_admin_user,
)
from neos.api.handlers import query_handlers, workflow_stream_handlers
from neos.api.models.query_models import QueryRequest, WorkflowStreamRequest
from neos.api.services.query_service import QueryService


API_PREFIX = "/api/v1"
RESOURCE_NOT_FOUND = {"detail": "Resource not found"}


def _load_production_app():
    import neos.main as main_module

    return main_module, main_module.app


def test_production_main_imports_in_clean_subprocess_without_test_bridge():
    env = os.environ.copy()
    env["GOOGLE_API_KEY"] = "test-key"
    env["JWT_SECRET_KEY"] = "neos-test-only-secret-key-2026-07-04"
    env["DEBUG"] = "false"

    result = subprocess.run(
        [sys.executable, "-c", "import neos.main"],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _user(user_id: str = "owner", *, is_admin: bool = False):
    return SimpleNamespace(
        user_id=user_id,
        is_active=True,
        is_admin=is_admin,
        role="admin" if is_admin else "user",
    )


async def _unauthenticated():
    raise HTTPException(status_code=401, detail="Authentication required")


def _query_app(current_user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(query_handlers.router, prefix=API_PREFIX)
    app.include_router(workflow_stream_handlers.router, prefix=API_PREFIX)
    app.dependency_overrides[get_current_active_user] = (
        (lambda: current_user) if current_user is not None else _unauthenticated
    )
    return app


def _effective_http_routes(app: FastAPI):
    routes = []
    for registered_route in app.routes:
        if hasattr(registered_route, "effective_route_contexts"):
            routes.extend(registered_route.effective_route_contexts())
        elif hasattr(registered_route, "dependant"):
            routes.append(registered_route)
    return routes


def _route(app: FastAPI, path: str, method: str) -> APIRoute:
    return next(
        route
        for route in _effective_http_routes(app)
        if route.path == path
        and method in route.methods
    )


def _dependency_names(route: APIRoute) -> set[str]:
    return {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
    }


def _install_query_service_defaults(monkeypatch):
    defaults = {
        "get_or_create_user": None,
        "process_query_workflow": {
            "success": True,
            "response": "ok",
            "session_id": "s1",
            "metadata": {},
            "execution_time_ms": 1,
            "quality_score": 1.0,
            "errors": [],
        },
        "save_query_history_background": None,
        "check_system_health": {
            "status": "healthy",
            "timestamp": "2026-07-04T00:00:00",
            "services": {},
        },
        "get_trending_queries": [],
        "get_related_queries": [],
        "get_user_query_history": [],
        "get_system_stats": {},
        "get_hyper_research_report": None,
        "list_hyper_research_reports": {
            "success": True,
            "reports": [],
            "total_count": 0,
        },
    }
    mocks = {}
    for method_name, return_value in defaults.items():
        mock = AsyncMock(return_value=return_value)
        monkeypatch.setattr(QueryService, method_name, mock)
        mocks[method_name] = mock
    return mocks


def _install_stream_defaults(monkeypatch):
    async def execute_workflow_with_streaming(**kwargs):
        await kwargs["callback"].on_workflow_complete(
            {
                "success": True,
                "response": "ok",
                "metadata": {},
                "execution_time_ms": 1,
                "quality_score": 1.0,
                "errors": [],
            }
        )

    execute = AsyncMock(side_effect=execute_workflow_with_streaming)
    create_session = Mock(return_value=SimpleNamespace(user_id="attacker"))
    monkeypatch.setattr(
        workflow_stream_handlers,
        "execute_workflow_with_streaming",
        execute,
    )
    monkeypatch.setattr(
        workflow_stream_handlers.stream_manager,
        "get_session",
        Mock(return_value=None),
    )
    monkeypatch.setattr(
        workflow_stream_handlers.stream_manager,
        "create_session",
        create_session,
    )
    return execute, create_session


def test_all_query_http_routes_have_an_explicit_public_owner_or_admin_classification():
    app = _query_app()
    expected = {
        (f"{API_PREFIX}/query", "POST"): "get_current_active_user",
        (f"{API_PREFIX}/health", "GET"): None,
        (f"{API_PREFIX}/trending", "GET"): None,
        (f"{API_PREFIX}/related/{{query_id}}", "GET"): None,
        (f"{API_PREFIX}/history/{{user_id}}", "GET"): "get_current_active_user",
        (f"{API_PREFIX}/cache/{{cache_key}}", "DELETE"): "get_current_admin_user",
        (f"{API_PREFIX}/stats/system", "GET"): "get_current_admin_user",
        (
            f"{API_PREFIX}/hyper-research/{{report_uuid}}",
            "GET",
        ): "get_current_active_user",
        (f"{API_PREFIX}/hyper-research", "GET"): "get_current_active_user",
        (f"{API_PREFIX}/query/stream", "POST"): "get_current_active_user",
    }
    actual_http_routes = {
        (route.path, method)
        for route in _effective_http_routes(app)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }

    assert actual_http_routes == set(expected)
    for route_key, dependency_name in expected.items():
        dependencies = _dependency_names(_route(app, *route_key))
        if dependency_name is None:
            assert not dependencies.intersection(
                {"get_current_active_user", "get_current_admin_user"}
            )
        else:
            assert dependency_name in dependencies


def test_production_query_workflow_routes_have_explicit_authorization_matrix():
    _, production_app = _load_production_app()
    expected = {
        (f"{API_PREFIX}/query", "POST"): "get_current_active_user",
        (f"{API_PREFIX}/health", "GET"): None,
        (f"{API_PREFIX}/trending", "GET"): None,
        (f"{API_PREFIX}/related/{{query_id}}", "GET"): None,
        (f"{API_PREFIX}/history/{{user_id}}", "GET"): "get_current_active_user",
        (f"{API_PREFIX}/cache/{{cache_key}}", "DELETE"): "get_current_admin_user",
        (f"{API_PREFIX}/stats/system", "GET"): "get_current_admin_user",
        (
            f"{API_PREFIX}/hyper-research/{{report_uuid}}",
            "GET",
        ): "get_current_active_user",
        (f"{API_PREFIX}/hyper-research", "GET"): "get_current_active_user",
        (f"{API_PREFIX}/query/stream", "POST"): "get_current_active_user",
        (f"{API_PREFIX}/multimodal/query", "POST"): "get_current_active_user",
        (
            f"{API_PREFIX}/multimodal/image/analyze",
            "POST",
        ): "get_current_active_user",
        (f"{API_PREFIX}/multimodal/supported-types", "GET"): None,
        (f"{API_PREFIX}/multimodal/health", "GET"): None,
        (f"{API_PREFIX}/unified/process", "POST"): "get_current_active_user",
        (
            f"{API_PREFIX}/unified/process/stream",
            "POST",
        ): "get_current_active_user",
        (
            f"{API_PREFIX}/unified/process/upload",
            "POST",
        ): "get_current_active_user",
        (
            f"{API_PREFIX}/unified/process/upload/stream",
            "POST",
        ): "get_current_active_user",
        (f"{API_PREFIX}/unified/health", "GET"): None,
        (f"{API_PREFIX}/deep-research/start", "POST"): "get_current_active_user",
        (
            f"{API_PREFIX}/deep-research/{{report_id}}/stream",
            "GET",
        ): "get_owned_deep_research_report",
        (
            f"{API_PREFIX}/deep-research/{{report_id}}",
            "GET",
        ): "get_owned_deep_research_report",
        (
            f"{API_PREFIX}/conversations/{{conversation_id}}/deep-research",
            "GET",
        ): "get_owned_conversation",
        (
            f"{API_PREFIX}/chat/conversations/{{conversation_id}}/messages/similarity",
            "POST",
        ): "get_owned_conversation",
        (
            f"{API_PREFIX}/chat/conversations/{{conversation_id}}/messages/similarity/stream",
            "POST",
        ): "get_owned_conversation",
        (
            f"{API_PREFIX}/chat/conversations/{{conversation_id}}/messages/similarity/cross-conversation",
            "POST",
        ): "get_owned_conversation",
        (
            f"{API_PREFIX}/chat/conversations/{{conversation_id}}/messages/similarity/high-confidence",
            "POST",
        ): "get_owned_conversation",
        (
            f"{API_PREFIX}/chat/conversations/{{conversation_id}}/similarity/config",
            "GET",
        ): "get_owned_conversation",
        (
            f"{API_PREFIX}/chat/conversations/{{conversation_id}}/similarity/analytics",
            "GET",
        ): "get_owned_conversation",
        (f"{API_PREFIX}/research/async", "POST"): "get_current_active_user",
        (
            f"{API_PREFIX}/research/async/{{job_id}}/status",
            "GET",
        ): "get_current_active_user",
        (
            f"{API_PREFIX}/research/stream/{{session_id}}",
            "GET",
        ): "get_current_active_user",
    }
    actual = {
        (route.path, method): _dependency_names(route)
        for route in _effective_http_routes(production_app)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"} and (route.path, method) in expected
    }

    assert set(actual) == set(expected)
    for route_key, dependency_name in expected.items():
        dependencies = actual[route_key]
        if dependency_name is None:
            assert not dependencies.intersection(
                {
                    "get_current_active_user",
                    "get_current_admin_user",
                    "get_owned_conversation",
                    "get_owned_deep_research_report",
                    "get_readable_conversation",
                }
            )
        else:
            assert dependency_name in dependencies


def test_query_compatibility_user_ids_are_optional_and_deprecated():
    query = QueryRequest(query="hello")
    stream = WorkflowStreamRequest(query="hello")

    assert query.user_id is None
    assert stream.user_id is None
    assert QueryRequest.model_json_schema()["properties"]["user_id"]["deprecated"] is True
    assert (
        WorkflowStreamRequest.model_json_schema()["properties"]["user_id"]["deprecated"]
        is True
    )


@pytest.mark.asyncio
async def test_process_query_uses_authenticated_user(monkeypatch):
    process = AsyncMock(
        return_value={
            "success": True,
            "response": "ok",
            "session_id": "s1",
            "metadata": {},
            "execution_time_ms": 1,
            "quality_score": 1.0,
            "errors": [],
        }
    )
    get_user = AsyncMock()
    monkeypatch.setattr(QueryService, "get_or_create_user", get_user)
    monkeypatch.setattr(QueryService, "process_query_workflow", process)

    await query_handlers.process_query(
        QueryRequest(query="hello", user_id="attacker", session_id="s1"),
        BackgroundTasks(),
        current_user=_user("owner"),
    )

    get_user.assert_awaited_once_with("owner")
    assert process.await_args.kwargs["user_id"] == "owner"


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        ("POST", f"{API_PREFIX}/query", {"json": {"query": "hello", "user_id": "attacker"}}),
        ("GET", f"{API_PREFIX}/history/attacker", {}),
        ("DELETE", f"{API_PREFIX}/cache/key", {}),
        ("GET", f"{API_PREFIX}/stats/system", {}),
        ("GET", f"{API_PREFIX}/hyper-research/report-1", {}),
        ("GET", f"{API_PREFIX}/hyper-research", {"params": {"user_id": "attacker"}}),
        (
            "POST",
            f"{API_PREFIX}/query/stream",
            {"json": {"query": "hello", "user_id": "attacker", "session_id": "s1"}},
        ),
    ],
)
def test_private_query_routes_reject_unauthenticated_before_side_effects(
    monkeypatch,
    method,
    path,
    request_kwargs,
):
    service_mocks = _install_query_service_defaults(monkeypatch)
    execute, create_session = _install_stream_defaults(monkeypatch)
    cache_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(query_handlers.cache_manager, "delete", cache_delete)

    with TestClient(_query_app()) as client:
        response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401
    for service_mock in service_mocks.values():
        service_mock.assert_not_awaited()
    cache_delete.assert_not_awaited()
    execute.assert_not_awaited()
    create_session.assert_not_called()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{API_PREFIX}/health"),
        ("GET", f"{API_PREFIX}/trending"),
        ("GET", f"{API_PREFIX}/related/7"),
    ],
)
def test_public_query_routes_remain_public(monkeypatch, method, path):
    _install_query_service_defaults(monkeypatch)

    with TestClient(_query_app()) as client:
        response = client.request(method, path)

    assert response.status_code == 200


def test_cross_user_history_is_hidden_before_service_call(monkeypatch):
    history = AsyncMock(return_value=[{"query": "private"}])
    monkeypatch.setattr(QueryService, "get_user_query_history", history)

    with TestClient(_query_app(_user("owner"))) as client:
        response = client.get(f"{API_PREFIX}/history/attacker")

    assert response.status_code == 404
    assert response.json() == RESOURCE_NOT_FOUND
    history.assert_not_awaited()


def test_owner_history_uses_authenticated_identity(monkeypatch):
    history = AsyncMock(return_value=[])
    monkeypatch.setattr(QueryService, "get_user_query_history", history)

    with TestClient(_query_app(_user("owner"))) as client:
        response = client.get(f"{API_PREFIX}/history/owner?limit=7&offset=2")

    assert response.status_code == 200
    history.assert_awaited_once_with("owner", 7, 2)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", f"{API_PREFIX}/cache/key"),
        ("GET", f"{API_PREFIX}/stats/system"),
    ],
)
def test_query_admin_routes_reject_non_admin_before_side_effects(
    monkeypatch,
    method,
    path,
):
    stats = AsyncMock(return_value={})
    cache_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(QueryService, "get_system_stats", stats)
    monkeypatch.setattr(query_handlers.cache_manager, "delete", cache_delete)

    with TestClient(_query_app(_user("owner"))) as client:
        response = client.request(method, path)

    assert response.status_code == 403
    stats.assert_not_awaited()
    cache_delete.assert_not_awaited()


def test_query_admin_routes_allow_admin(monkeypatch):
    stats = AsyncMock(return_value={"ok": True})
    cache_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(QueryService, "get_system_stats", stats)
    monkeypatch.setattr(query_handlers.cache_manager, "delete", cache_delete)

    with TestClient(_query_app(_user("admin", is_admin=True))) as client:
        cache_response = client.delete(f"{API_PREFIX}/cache/key")
        stats_response = client.get(f"{API_PREFIX}/stats/system")

    assert cache_response.status_code == 200
    assert stats_response.status_code == 200
    cache_delete.assert_awaited_once_with("key")
    stats.assert_awaited_once_with()


@pytest.mark.parametrize(
    "report",
    [None, {"metadata": {"user_id": "other"}}],
    ids=["missing", "non-owner"],
)
def test_hyper_research_detail_hides_missing_and_non_owner(monkeypatch, report):
    get_report = AsyncMock(return_value=report)
    monkeypatch.setattr(QueryService, "get_hyper_research_report", get_report)

    with TestClient(_query_app(_user("owner"))) as client:
        response = client.get(f"{API_PREFIX}/hyper-research/report-1")

    assert response.status_code == 404
    assert response.json() == RESOURCE_NOT_FOUND
    get_report.assert_awaited_once_with("report-1")


def test_hyper_research_list_uses_authenticated_identity(monkeypatch):
    list_reports = AsyncMock(
        return_value={"success": True, "reports": [], "total_count": 0}
    )
    monkeypatch.setattr(QueryService, "list_hyper_research_reports", list_reports)

    with TestClient(_query_app(_user("owner"))) as client:
        response = client.get(
            f"{API_PREFIX}/hyper-research",
            params={"user_id": "attacker", "status": "completed"},
        )

    assert response.status_code == 200
    list_reports.assert_awaited_once_with("owner", "completed", 50, 0)


@pytest.mark.asyncio
async def test_stream_query_rejects_cross_user_session_before_response(monkeypatch):
    claim_session = Mock(side_effect=PermissionError("foreign session"))
    execute = AsyncMock()
    monkeypatch.setattr(
        workflow_stream_handlers.stream_manager,
        "claim_session",
        claim_session,
        raising=False,
    )
    monkeypatch.setattr(
        workflow_stream_handlers,
        "execute_workflow_with_streaming",
        execute,
    )

    with pytest.raises(HTTPException) as exc:
        await workflow_stream_handlers.stream_query(
            WorkflowStreamRequest(query="hello", session_id="s1"),
            SimpleNamespace(headers={}),
            current_user=_user("user-a"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    claim_session.assert_called_once_with("s1", "user-a")
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_query_uses_authenticated_user_and_creates_only_new_session(monkeypatch):
    captured = {}

    async def execute_workflow_with_streaming(**kwargs):
        captured.update(kwargs)
        await kwargs["callback"].on_workflow_complete(
            {
                "success": True,
                "response": "ok",
                "metadata": {},
                "execution_time_ms": 1,
                "quality_score": 1.0,
                "errors": [],
            }
        )

    claimed_session = SimpleNamespace(user_id="owner")
    claim_session = Mock(return_value=claimed_session)
    monkeypatch.setattr(
        workflow_stream_handlers.stream_manager,
        "claim_session",
        claim_session,
        raising=False,
    )
    monkeypatch.setattr(
        workflow_stream_handlers,
        "execute_workflow_with_streaming",
        execute_workflow_with_streaming,
    )

    response = await workflow_stream_handlers.stream_query(
        WorkflowStreamRequest(
            query="hello",
            user_id="attacker",
            session_id="s1",
            stream_options={"include_heartbeat": False, "enable_db_logging": False},
        ),
        SimpleNamespace(headers={}),
        current_user=_user("owner"),
    )
    payloads = []
    async for chunk in response.body_iterator:
        payloads.append(json.loads(chunk.removeprefix("data: ").strip()))
        if payloads[-1]["event"] == "completed":
            break

    claim_session.assert_called_once_with("s1", "owner")
    assert captured["user_id"] == "owner"
    assert "Access-Control-Allow-Origin" not in response.headers


def test_operational_routes_install_admin_dependency_and_root_stays_public():
    _, production_app = _load_production_app()
    expected = {
        ("/metrics", "GET"): "get_current_admin_user",
        (f"{API_PREFIX}/metrics/stats", "GET"): "get_current_admin_user",
        ("/info", "GET"): "get_current_admin_user",
        ("/", "GET"): None,
        (f"{API_PREFIX}/health", "GET"): None,
    }

    for route_key, dependency_name in expected.items():
        dependencies = _dependency_names(_route(production_app, *route_key))
        if dependency_name is None:
            assert "get_current_admin_user" not in dependencies
        else:
            assert dependency_name in dependencies


@pytest.mark.parametrize(
    "path",
    ["/metrics", f"{API_PREFIX}/metrics/stats", "/info"],
)
def test_operational_routes_reject_unauthenticated_requests(path):
    _, production_app = _load_production_app()
    previous_overrides = production_app.dependency_overrides.copy()
    production_app.dependency_overrides[get_current_active_user] = _unauthenticated
    client = TestClient(production_app)
    try:
        response = client.get(path)
    finally:
        client.close()
        production_app.dependency_overrides = previous_overrides

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/metrics", f"{API_PREFIX}/metrics/stats", "/info"],
)
def test_operational_routes_reject_non_admin(path):
    _, production_app = _load_production_app()
    previous_overrides = production_app.dependency_overrides.copy()
    production_app.dependency_overrides[get_current_active_user] = lambda: _user("owner")
    client = TestClient(production_app)
    try:
        response = client.get(path)
    finally:
        client.close()
        production_app.dependency_overrides = previous_overrides

    assert response.status_code == 403


def _debug_app(main_module, current_user=None) -> FastAPI:
    app = FastAPI()
    app.add_api_route(
        "/debug/test-workflow",
        main_module.debug_test_workflow,
        methods=["GET"],
    )
    app.add_api_route(
        "/debug/cache-stats",
        main_module.debug_cache_stats,
        methods=["GET"],
    )
    app.dependency_overrides[get_current_active_user] = (
        (lambda: current_user) if current_user is not None else _unauthenticated
    )
    return app


@pytest.mark.parametrize("path", ["/debug/test-workflow", "/debug/cache-stats"])
@pytest.mark.parametrize(
    ("current_user", "expected_status"),
    [(None, 401), (_user("member"), 403)],
)
def test_debug_operational_routes_deny_before_side_effects(
    monkeypatch,
    path,
    current_user,
    expected_status,
):
    main_module, _ = _load_production_app()
    execute = AsyncMock()
    redis_info = AsyncMock()
    monkeypatch.setattr(main_module.multi_agent_workflow, "execute_workflow", execute)
    monkeypatch.setattr(
        main_module.cache_manager,
        "redis_client",
        SimpleNamespace(info=redis_info),
    )

    with TestClient(_debug_app(main_module, current_user)) as client:
        response = client.get(path)

    assert response.status_code == expected_status
    execute.assert_not_awaited()
    redis_info.assert_not_awaited()


def test_debug_operational_routes_use_admin_identity(monkeypatch):
    main_module, _ = _load_production_app()
    execute = AsyncMock(return_value={"success": True})
    redis_info = AsyncMock(return_value={"connected_clients": 1})
    monkeypatch.setattr(main_module.multi_agent_workflow, "execute_workflow", execute)
    monkeypatch.setattr(
        main_module.cache_manager,
        "redis_client",
        SimpleNamespace(info=redis_info),
    )

    with TestClient(_debug_app(main_module, _user("admin-1", is_admin=True))) as client:
        workflow_response = client.get("/debug/test-workflow")
        cache_response = client.get("/debug/cache-stats")

    assert workflow_response.status_code == 200
    assert cache_response.status_code == 200
    assert execute.await_args.args[0]["user_id"] == "admin-1"
    redis_info.assert_awaited_once_with()


def test_debug_true_production_graph_installs_admin_dependencies():
    env = os.environ.copy()
    env["GOOGLE_API_KEY"] = "test-key"
    env["JWT_SECRET_KEY"] = "neos-test-only-secret-key-2026-07-04"
    env["DEBUG"] = "true"
    script = """
import json
from fastapi.routing import APIRoute
from neos.main import app

result = {}
for route in app.routes:
    routes = route.effective_route_contexts() if hasattr(route, "effective_route_contexts") else [route]
    for effective in routes:
        if isinstance(effective, APIRoute) and effective.path.startswith("/debug/"):
            result[effective.path] = [
                dependency.call.__name__
                for dependency in effective.dependant.dependencies
            ]
print("DEBUG_ROUTES=" + json.dumps(result, sort_keys=True))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    marker = next(
        line for line in result.stdout.splitlines() if line.startswith("DEBUG_ROUTES=")
    )
    routes = json.loads(marker.removeprefix("DEBUG_ROUTES="))
    assert set(routes) == {"/debug/test-workflow", "/debug/cache-stats"}
    assert all("get_current_admin_user" in dependencies for dependencies in routes.values())


def test_public_root_exposes_only_minimum_information(monkeypatch):
    main_module, production_app = _load_production_app()
    monkeypatch.setattr(main_module, "IS_DEBUG", False)
    client = TestClient(production_app)
    try:
        response = client.get("/")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {
        "name": "Multi-Agent AI System",
        "version": main_module.__VERSION__,
        "status": "running",
        "health": f"{API_PREFIX}/health",
    }


def test_public_root_adds_docs_path_only_in_debug(monkeypatch):
    main_module, production_app = _load_production_app()
    monkeypatch.setattr(main_module, "IS_DEBUG", True)
    client = TestClient(production_app)
    try:
        response = client.get("/")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"
    assert set(response.json()) == {"name", "version", "status", "health", "docs"}
