import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import get_current_active_user
from neos.api.handlers import multimodal_handlers, unified_handlers
from neos.api.models.unified_models import (
    UnifiedProcessingRequest,
    UnifiedStreamEvent,
)
from neos.api.services.multimodal_service import MultimodalService
from neos.api.services.query_service import QueryService
from neos.api.services.unified_processor import UnifiedProcessingService


def _user(user_id: str = "owner"):
    return SimpleNamespace(user_id=user_id, is_active=True)


async def _unauthenticated():
    raise HTTPException(status_code=401, detail="Authentication required")


def _app(current_user=None):
    app = FastAPI()
    app.include_router(
        multimodal_handlers.router,
        prefix="/api/v1/multimodal",
    )
    app.include_router(unified_handlers.router)
    app.dependency_overrides[get_current_active_user] = (
        (lambda: current_user) if current_user else _unauthenticated
    )
    return app


def _upload(filename: str = "image.png", content_type: str = "image/png"):
    return UploadFile(
        filename=filename,
        file=io.BytesIO(b"image-bytes"),
        headers={"content-type": content_type},
    )


def _unified_result(session_id: str = "s1"):
    return {
        "success": True,
        "session_id": session_id,
        "documents_processed": [],
        "response": "ok",
        "quality_score": 1.0,
        "execution_time_ms": 1,
        "metadata": {},
        "errors": [],
    }


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        (
            "POST",
            "/api/v1/multimodal/query",
            {
                "data": {"query": "hello", "user_id": "attacker"},
                "files": [("files", ("image.png", b"image", "image/png"))],
            },
        ),
        (
            "POST",
            "/api/v1/multimodal/image/analyze",
            {
                "data": {"user_id": "attacker"},
                "files": {"image": ("image.png", b"image", "image/png")},
            },
        ),
        (
            "POST",
            "/api/v1/unified/process",
            {"json": {"query": "hello", "user_id": "attacker"}},
        ),
        (
            "POST",
            "/api/v1/unified/process/stream",
            {"json": {"query": "hello", "user_id": "attacker"}},
        ),
        (
            "POST",
            "/api/v1/unified/process/upload",
            {
                "data": {"query": "hello", "user_id": "attacker"},
                "files": [("files", ("doc.txt", b"private", "text/plain"))],
            },
        ),
        (
            "POST",
            "/api/v1/unified/process/upload/stream",
            {
                "data": {"query": "hello", "user_id": "attacker"},
                "files": [("files", ("doc.txt", b"private", "text/plain"))],
            },
        ),
    ],
)
def test_multimodal_and_unified_routes_reject_unauthenticated_before_services(
    monkeypatch,
    method,
    path,
    request_kwargs,
):
    multimodal = AsyncMock(return_value={})
    analyze = AsyncMock(return_value={})
    process = AsyncMock(return_value=_unified_result())
    get_user = AsyncMock()
    stream_started = Mock()

    async def process_stream(_request):
        stream_started()
        yield UnifiedStreamEvent(event="completed", session_id="s1")

    monkeypatch.setattr(QueryService, "get_or_create_user", get_user)
    monkeypatch.setattr(
        MultimodalService,
        "process_multimodal_query",
        multimodal,
    )
    monkeypatch.setattr(MultimodalService, "analyze_image", analyze)
    monkeypatch.setattr(UnifiedProcessingService, "process", process)
    monkeypatch.setattr(UnifiedProcessingService, "process_stream", process_stream)

    with TestClient(_app()) as client:
        response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401
    multimodal.assert_not_awaited()
    analyze.assert_not_awaited()
    process.assert_not_awaited()
    get_user.assert_not_awaited()
    stream_started.assert_not_called()


@pytest.mark.asyncio
async def test_multimodal_query_ignores_spoofed_user(monkeypatch):
    get_user = AsyncMock()
    process = AsyncMock(
        return_value={
            "success": True,
            "response": "ok",
            "session_id": "s1",
            "input_type": "multimodal",
            "metadata": {},
            "processing_time_ms": 1,
            "errors": [],
            "warnings": [],
        }
    )
    monkeypatch.setattr(QueryService, "get_or_create_user", get_user)
    monkeypatch.setattr(MultimodalService, "convert_upload_files_to_dict", AsyncMock(return_value=[]))
    monkeypatch.setattr(MultimodalService, "process_multimodal_query", process)

    await multimodal_handlers.process_multimodal_query(
        background_tasks=SimpleNamespace(),
        query="hello",
        files=[_upload()],
        user_id="attacker",
        session_id="s1",
        language="ko",
        current_user=_user(),
    )

    get_user.assert_awaited_once_with("owner")
    assert process.await_args.kwargs["user_id"] == "owner"


@pytest.mark.asyncio
async def test_image_analysis_ignores_spoofed_user(monkeypatch):
    analyze = AsyncMock(
        return_value={
            "success": True,
            "filename": "image.png",
            "description": "ok",
            "objects": [],
            "image_metadata": {},
            "processing_time_ms": 1,
        }
    )
    monkeypatch.setattr(MultimodalService, "analyze_image", analyze)

    await multimodal_handlers.analyze_image(
        image=_upload(),
        query=None,
        user_id="attacker",
        language="ko",
        current_user=_user(),
    )

    assert analyze.await_args.kwargs["user_id"] == "owner"


@pytest.mark.asyncio
async def test_unified_json_routes_ignore_spoofed_user_and_remove_wildcard_cors(
    monkeypatch,
):
    process = AsyncMock(return_value=_unified_result())
    captured = {}

    async def process_stream(request):
        captured["request"] = request
        yield UnifiedStreamEvent(
            event="completed",
            session_id="s1",
            data={"response": "ok"},
        )

    monkeypatch.setattr(UnifiedProcessingService, "process", process)
    monkeypatch.setattr(UnifiedProcessingService, "process_stream", process_stream)
    spoofed = UnifiedProcessingRequest(query="hello", user_id="attacker", session_id="s1")

    await unified_handlers.process_unified(spoofed, current_user=_user())
    response = await unified_handlers.process_unified_stream(
        spoofed,
        current_user=_user(),
    )
    async for _ in response.body_iterator:
        break

    assert process.await_args.args[0].user_id == "owner"
    assert captured["request"].user_id == "owner"
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.asyncio
async def test_unified_upload_routes_ignore_spoofed_user_and_remove_wildcard_cors(
    monkeypatch,
):
    process = AsyncMock(return_value=_unified_result())
    captured = {}

    async def process_stream(request):
        captured["request"] = request
        yield UnifiedStreamEvent(
            event="completed",
            session_id="s1",
            data={"response": "ok"},
        )

    monkeypatch.setattr(UnifiedProcessingService, "process", process)
    monkeypatch.setattr(UnifiedProcessingService, "process_stream", process_stream)

    await unified_handlers.process_with_file_upload(
        query="hello",
        files=[_upload("doc.txt", "text/plain")],
        mode="auto",
        enable_vision=True,
        bypass_cache=False,
        session_id="s1",
        user_id="attacker",
        current_user=_user(),
    )
    response = await unified_handlers.process_with_file_upload_stream(
        query="hello",
        files=[_upload("doc.txt", "text/plain")],
        mode="auto",
        enable_vision=True,
        bypass_cache=False,
        session_id="s1",
        user_id="attacker",
        current_user=_user(),
    )
    async for _ in response.body_iterator:
        break

    assert process.await_args.args[0].user_id == "owner"
    assert captured["request"].user_id == "owner"
    assert "Access-Control-Allow-Origin" not in response.headers


def test_unified_json_user_id_is_optional_deprecated_compatibility_field():
    request = UnifiedProcessingRequest(query="hello")
    schema = UnifiedProcessingRequest.model_json_schema()

    assert request.user_id is None
    assert schema["properties"]["user_id"]["deprecated"] is True
