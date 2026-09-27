from datetime import datetime
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies import resource_access
from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import document_handlers
from neos.api.services.document_service import DocumentProcessor, DocumentService
from neos.database.connection import get_db


BASE_PATH = "/api/v1/documents/documents"


def _document(*, user_id: str = "owner", document_id: int = 7):
    return SimpleNamespace(
        id=document_id,
        user_id=user_id,
        filename="private.txt",
        original_filename="private.txt",
        file_size=7,
        mime_type="text/plain",
        storage_provider="local",
        storage_url=None,
        processing_status="completed",
        kg_extracted=True,
        embedding_processed=True,
        fts_indexed=True,
        created_at=datetime(2026, 7, 2),
        metadata={"classification": "private"},
    )


def _document_app(current_user=None) -> FastAPI:
    app = FastAPI()
    # Preserve the production double-prefix while its URL design remains out of scope.
    app.include_router(document_handlers.router, prefix="/api/v1/documents")

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
    return app


def _route(app: FastAPI, path: str, method: str):
    effective_routes = []
    for registered_route in app.routes:
        if hasattr(registered_route, "effective_route_contexts"):
            effective_routes.extend(registered_route.effective_route_contexts())
        elif hasattr(registered_route, "methods"):
            effective_routes.append(registered_route)
    return next(
        route
        for route in effective_routes
        if route.path == path and method in route.methods
    )


def _install_service_defaults(monkeypatch):
    defaults = {
        "upload_and_process_document": _document(),
        "get_document_by_id": _document(),
        "delete_document": True,
        "delete_document_for_user": True,
    }
    mocks = {}
    for method_name, return_value in defaults.items():
        mock = AsyncMock(return_value=return_value)
        monkeypatch.setattr(DocumentService, method_name, mock, raising=False)
        mocks[method_name] = mock
    return mocks


def test_document_routes_preserve_double_prefix_and_install_auth_dependencies():
    app = _document_app()
    expected = {
        (f"{BASE_PATH}/upload", "POST"): "get_current_active_user",
        (f"{BASE_PATH}/{{document_id}}", "GET"): "get_owned_document",
        (f"{BASE_PATH}/{{document_id}}", "DELETE"): "get_owned_document",
    }

    for (path, method), dependency_name in expected.items():
        dependency_names = {
            dependency.call.__name__
            for dependency in _route(app, path, method).dependant.dependencies
        }
        assert dependency_name in dependency_names


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        (
            "POST",
            f"{BASE_PATH}/upload",
            {
                "files": {"file": ("private.txt", b"private", "text/plain")},
                "data": {"user_id": "attacker"},
            },
        ),
        ("GET", f"{BASE_PATH}/7", {}),
        ("DELETE", f"{BASE_PATH}/7", {}),
    ],
)
def test_all_document_routes_reject_unauthenticated_requests_before_service_calls(
    monkeypatch,
    method,
    path,
    request_kwargs,
):
    service_mocks = _install_service_defaults(monkeypatch)

    with TestClient(_document_app()) as client:
        response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401
    for service_mock in service_mocks.values():
        service_mock.assert_not_awaited()


def test_upload_uses_authenticated_user_without_requiring_compatibility_user_id(
    monkeypatch,
):
    upload = AsyncMock(return_value=_document())
    monkeypatch.setattr(
        document_handlers.DocumentService,
        "upload_and_process_document",
        upload,
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_document_app(current_user)) as client:
        response = client.post(
            f"{BASE_PATH}/upload",
            files={"file": ("private.txt", b"private", "text/plain")},
        )

    assert response.status_code == 200
    assert upload.await_args.kwargs["user_id"] == "owner"


@pytest.mark.parametrize(
    "looked_up_document",
    [None, _document(user_id="other")],
    ids=["missing", "non-owner"],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{BASE_PATH}/7"),
        ("DELETE", f"{BASE_PATH}/7"),
    ],
)
def test_private_document_routes_hide_missing_and_non_owner_resources_before_service(
    monkeypatch,
    looked_up_document,
    method,
    path,
):
    service_mocks = _install_service_defaults(monkeypatch)
    lookup = AsyncMock(return_value=looked_up_document)
    monkeypatch.setattr(resource_access, "_get_document_by_id", lookup)
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_document_app(current_user)) as client:
        response = client.request(method, path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    lookup.assert_awaited_once_with(7)
    for service_mock in service_mocks.values():
        service_mock.assert_not_awaited()


def test_owner_document_routes_use_authorized_document_id(monkeypatch):
    owned_document = _document(document_id=17)
    lookup = AsyncMock(return_value=owned_document)
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(resource_access, "_get_document_by_id", lookup)
    monkeypatch.setattr(
        document_handlers.DocumentService,
        "delete_document_for_user",
        delete,
        raising=False,
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_document_app(current_user)) as client:
        detail_response = client.get(f"{BASE_PATH}/7")
        delete_response = client.delete(f"{BASE_PATH}/7")

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == 17
    assert delete_response.status_code == 200
    delete.assert_awaited_once_with(17, "owner")


def test_delete_race_uses_the_same_resource_not_found_response(monkeypatch):
    lookup = AsyncMock(return_value=_document())
    delete = AsyncMock(return_value=False)
    monkeypatch.setattr(resource_access, "_get_document_by_id", lookup)
    monkeypatch.setattr(
        document_handlers.DocumentService,
        "delete_document_for_user",
        delete,
    )
    current_user = SimpleNamespace(user_id="owner", is_active=True)

    with TestClient(_document_app(current_user)) as client:
        response = client.delete(f"{BASE_PATH}/7")

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}


@pytest.mark.asyncio
async def test_delete_document_for_user_requires_owned_lookup(monkeypatch):
    lookup = AsyncMock(return_value=None)
    processor_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(
        DocumentService,
        "get_document_for_user",
        lookup,
        raising=False,
    )
    monkeypatch.setattr(DocumentProcessor, "delete_document", processor_delete)

    assert await DocumentService.delete_document_for_user(7, "owner") is False
    lookup.assert_awaited_once_with(7, "owner")
    processor_delete.assert_not_awaited()
