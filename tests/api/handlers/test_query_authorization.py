import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import (
    get_current_active_user,
)
from neos.api.handlers import query_handlers
from neos.api.services.query_service import QueryService


API_PREFIX = "/api/v1"
RESOURCE_NOT_FOUND = {"detail": "Resource not found"}


def _load_production_app():
    import neos.main as main_module

    # neos.main captures IS_DEBUG at import time and only strips unauthenticated
    # WebSocket routes when it is false. Fail with the reason rather than with a
    # confusing route diff if the session was not pinned to production shape.
    assert not main_module.IS_DEBUG, (
        "neos.main was imported with DEBUG enabled, so these production-shape "
        "assertions cannot hold. Run pytest without DEBUG=true in the environment."
    )

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


def _has_auth_dependency(route: APIRoute) -> bool:
    dependency_names = _dependency_names(route)
    return any(
        name in {
            "get_current_user",
            "get_current_active_user",
            "get_current_admin_user",
        }
        or name.startswith("get_owned_")
        or name.startswith("get_readable_")
        for name in dependency_names
    )


def _is_allowed_public_http_route(path: str, method: str) -> bool:
    if method != "GET":
        return path.startswith(f"{API_PREFIX}/auth/")
    return (
        path == "/"
        or path.startswith(f"{API_PREFIX}/auth/")
        or path.endswith("/health")
    )


def _websocket_paths(app: FastAPI) -> set[str]:
    paths = set()
    for registered_route in app.routes:
        original_router = getattr(registered_route, "original_router", None)
        if original_router is not None:
            include_context = getattr(registered_route, "include_context", None)
            prefix = getattr(include_context, "prefix", "") if include_context else ""
            paths.update(
                f"{prefix}{route.path}"
                for route in original_router.routes
                if isinstance(route, APIWebSocketRoute)
            )
        elif isinstance(registered_route, APIWebSocketRoute):
            paths.add(registered_route.path)
    return paths


def _install_query_service_defaults(monkeypatch):
    defaults = {
        "check_system_health": {
            "status": "healthy",
            "timestamp": "2026-07-04T00:00:00",
            "services": {},
        },
    }
    mocks = {}
    for method_name, return_value in defaults.items():
        mock = AsyncMock(return_value=return_value)
        monkeypatch.setattr(QueryService, method_name, mock)
        mocks[method_name] = mock
    return mocks


def test_all_query_http_routes_have_an_explicit_public_owner_or_admin_classification():
    app = _query_app()
    # 레거시 쿼리 API 를 걷어 낸 뒤(2026-09-27, `tests/api/test_retired_routes.py`)
    # 이 라우터에 남은 것은 공개 헬스 체크 하나다.
    expected = {
        (f"{API_PREFIX}/health", "GET"): None,
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
    # 레거시 쿼리 API 를 걷어 낸 뒤(2026-09-27, `tests/api/test_retired_routes.py`)
    # 이 라우터에 남은 것은 공개 헬스 체크 하나다.
    expected = {
        (f"{API_PREFIX}/health", "GET"): None,
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
                    "get_readable_conversation",
                }
            )
        else:
            assert dependency_name in dependencies


def test_production_app_exposes_only_allowed_public_http_routes():
    _, production_app = _load_production_app()

    unexpected_public_routes = sorted(
        (route.path, method)
        for route in _effective_http_routes(production_app)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
        and not _has_auth_dependency(route)
        and not _is_allowed_public_http_route(route.path, method)
    )

    assert unexpected_public_routes == []


def test_production_health_routes_remain_public():
    _, production_app = _load_production_app()

    authenticated_health_routes = sorted(
        (route.path, method)
        for route in _effective_http_routes(production_app)
        for method in route.methods
        if method == "GET"
        and route.path.endswith("/health")
        and _has_auth_dependency(route)
    )

    assert authenticated_health_routes == []


def test_production_app_exposes_only_authenticated_coding_websocket():
    _, production_app = _load_production_app()

    assert _websocket_paths(production_app) == {
        f"{API_PREFIX}/coding/ws",
        f"{API_PREFIX}/coding/workspace/ws",
        f"{API_PREFIX}/coding/pty/ws",
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{API_PREFIX}/health"),
    ],
)
def test_public_query_routes_remain_public(monkeypatch, method, path):
    _install_query_service_defaults(monkeypatch)

    with TestClient(_query_app()) as client:
        response = client.request(method, path)

    assert response.status_code == 200


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
