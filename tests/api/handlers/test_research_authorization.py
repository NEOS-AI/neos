import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.dependencies.auth import get_current_active_user, get_current_user
from neos.api.handlers import async_research_handlers, deep_research_handlers
from neos.api.models.deep_research_models import StartDeepResearchRequest
from neos.api.services.chat_service import ChatService
from neos.utils.cache import cache_manager


RESOURCE_NOT_FOUND = {"detail": "Resource not found"}


def _user(user_id: str = "owner"):
    return SimpleNamespace(user_id=user_id, is_active=True)


async def _unauthenticated():
    raise HTTPException(status_code=401, detail="Authentication required")


def _app(current_user=None):
    app = FastAPI()
    app.include_router(deep_research_handlers.router, prefix="/api/v1")
    app.include_router(async_research_handlers.router)
    override = (lambda: current_user) if current_user else _unauthenticated
    app.dependency_overrides[get_current_user] = override
    app.dependency_overrides[get_current_active_user] = override
    return app


def _conversation(user_id: str = "owner"):
    return {
        "conversation_id": "c1",
        "user_id": user_id,
        "visibility": "private",
    }


def _report(user_id: str = "owner"):
    return {
        "report_id": "r1",
        "user_id": user_id,
        "session_id": "s1",
        "research_topic": "private",
        "conversation_id": "c1",
        "initial_message_id": "m1",
        "research_status": "pending",
        "research_plan": {},
        "total_sections": 0,
        "total_sources": 0,
        "total_queries": 0,
        "quality_score": None,
        "completeness_score": None,
        "processing_time_ms": None,
        "created_at": datetime(2026, 7, 4),
        "started_at": None,
        "completed_at": None,
    }


@pytest.mark.parametrize("conversation", [None, _conversation("other")])
def test_deep_research_start_hides_missing_and_foreign_conversation_before_writes(
    monkeypatch,
    conversation,
):
    get_conversation = AsyncMock(return_value=conversation)
    add_message = AsyncMock()
    save_report = AsyncMock()
    cleanup = AsyncMock()
    monkeypatch.setattr(ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(ChatService, "add_message", add_message)
    monkeypatch.setattr(deep_research_handlers, "save_deep_research_report", save_report)
    monkeypatch.setattr(deep_research_handlers, "_cleanup_failed_research", cleanup)

    with TestClient(_app(_user())) as client:
        response = client.post(
            "/api/v1/deep-research/start",
            json={
                "user_id": "attacker",
                "conversation_id": "c1",
                "research_topic": "private",
            },
        )

    assert response.status_code == 404
    assert response.json() == RESOURCE_NOT_FOUND
    get_conversation.assert_awaited_once_with("c1")
    add_message.assert_not_awaited()
    save_report.assert_not_awaited()
    cleanup.assert_not_awaited()


def test_deep_research_start_uses_authenticated_identity(monkeypatch):
    monkeypatch.setattr(
        ChatService,
        "get_conversation",
        AsyncMock(return_value=_conversation()),
    )
    add_message = AsyncMock()
    save_report = AsyncMock(return_value="r1")
    monkeypatch.setattr(ChatService, "add_message", add_message)
    monkeypatch.setattr(deep_research_handlers, "save_deep_research_report", save_report)

    with TestClient(_app(_user())) as client:
        response = client.post(
            "/api/v1/deep-research/start",
            json={
                "user_id": "attacker",
                "conversation_id": "c1",
                "research_topic": "private",
                "session_id": "s1",
            },
        )

    assert response.status_code == 200
    assert save_report.await_args.kwargs["user_id"] == "owner"


def test_deep_research_user_id_is_optional_deprecated_compatibility_field():
    request = StartDeepResearchRequest(
        conversation_id="c1",
        research_topic="private",
    )
    schema = StartDeepResearchRequest.model_json_schema()

    assert request.user_id is None
    assert schema["properties"]["user_id"]["deprecated"] is True


@pytest.mark.parametrize("report", [None, _report("other")])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/deep-research/r1",
        "/api/v1/deep-research/r1/stream",
    ],
)
def test_deep_research_report_routes_hide_missing_and_foreign_before_data_reads(
    monkeypatch,
    report,
    path,
):
    get_report = AsyncMock(return_value=report)
    fetch_one = AsyncMock(return_value=("assistant",))
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(deep_research_handlers, "get_research_report", get_report)
    monkeypatch.setattr(deep_research_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(deep_research_handlers.db_manager, "fetch_all", fetch_all)

    with TestClient(_app(_user())) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert response.json() == RESOURCE_NOT_FOUND
    get_report.assert_awaited_once_with("r1")
    fetch_one.assert_not_awaited()
    fetch_all.assert_not_awaited()


def test_deep_research_owner_can_read_detail(monkeypatch):
    get_report = AsyncMock(return_value=_report())
    fetch_one = AsyncMock(return_value=("assistant",))
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(deep_research_handlers, "get_research_report", get_report)
    monkeypatch.setattr(deep_research_handlers.db_manager, "fetch_one", fetch_one)
    monkeypatch.setattr(deep_research_handlers.db_manager, "fetch_all", fetch_all)

    with TestClient(_app(_user())) as client:
        detail = client.get("/api/v1/deep-research/r1")

    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_deep_research_owner_opens_stream_after_owner_lookup(monkeypatch):
    fetch_one = AsyncMock(return_value=("assistant",))
    monkeypatch.setattr(deep_research_handlers.db_manager, "fetch_one", fetch_one)

    response = await deep_research_handlers.stream_deep_research(
        "r1",
        report=_report(),
    )

    assert response.status_code == 200
    fetch_one.assert_awaited_once()


@pytest.mark.parametrize("conversation", [None, _conversation("other")])
def test_conversation_research_list_hides_missing_and_foreign_before_query(
    monkeypatch,
    conversation,
):
    monkeypatch.setattr(
        ChatService,
        "get_conversation",
        AsyncMock(return_value=conversation),
    )
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(deep_research_handlers.db_manager, "fetch_all", fetch_all)

    with TestClient(_app(_user())) as client:
        response = client.get("/api/v1/conversations/c1/deep-research")

    assert response.status_code == 404
    assert response.json() == RESOURCE_NOT_FOUND
    fetch_all.assert_not_awaited()


def _install_fake_celery(monkeypatch, result):
    async_result = Mock(return_value=result)
    fake_module = SimpleNamespace(app=SimpleNamespace(AsyncResult=async_result))
    monkeypatch.setitem(sys.modules, "neos.workflow.celery_app", fake_module)
    return async_result


@pytest.mark.asyncio
async def test_async_research_start_records_job_owner(monkeypatch):
    monkeypatch.setattr(async_research_handlers.settings, "CELERY_ENABLED", True)
    apply_async = Mock(return_value=SimpleNamespace(id="job-1"))
    fake_tasks = SimpleNamespace(
        execute_workflow_async=SimpleNamespace(apply_async=apply_async)
    )
    monkeypatch.setitem(sys.modules, "neos.workflow.celery_tasks", fake_tasks)
    cache_set = AsyncMock(return_value=True)
    monkeypatch.setattr(cache_manager, "set", cache_set)

    response = await async_research_handlers.start_async_research(
        async_research_handlers.AsyncResearchRequest(query="private", session_id="s1"),
        current_user=_user(),
    )

    assert response.job_id == "job-1"
    cache_set.assert_awaited_once_with(
        "async_research_job_owner:job-1",
        "owner",
        ttl=86400,
    )


@pytest.mark.parametrize("job_owner", [None, "other"])
def test_async_job_status_hides_missing_and_foreign_before_celery_lookup(
    monkeypatch,
    job_owner,
):
    monkeypatch.setattr(async_research_handlers.settings, "CELERY_ENABLED", True)
    cache_get = AsyncMock(return_value=job_owner)
    monkeypatch.setattr(cache_manager, "get", cache_get)
    async_result = _install_fake_celery(monkeypatch, SimpleNamespace())

    with TestClient(_app(_user())) as client:
        response = client.get("/api/v1/research/async/job-1/status")

    assert response.status_code == 404
    assert response.json() == RESOURCE_NOT_FOUND
    async_result.assert_not_called()


def test_async_job_owner_can_read_status(monkeypatch):
    monkeypatch.setattr(async_research_handlers.settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    result = SimpleNamespace(status="PENDING", ready=lambda: False)
    async_result = _install_fake_celery(monkeypatch, result)

    with TestClient(_app(_user())) as client:
        response = client.get("/api/v1/research/async/job-1/status")

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    async_result.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_async_stream_rejects_foreign_claim_before_response_or_buffer(
    monkeypatch,
):
    claim = Mock(side_effect=PermissionError("foreign"))
    get_events = Mock()
    fake_stream_manager = SimpleNamespace(
        claim_session=claim,
        get_events_since=get_events,
    )
    monkeypatch.setattr(
        async_research_handlers,
        "stream_manager",
        fake_stream_manager,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc:
        await async_research_handlers.stream_research_progress(
            "s1",
            SimpleNamespace(is_disconnected=AsyncMock(return_value=True)),
            current_user=_user(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Resource not found"
    claim.assert_called_once_with("s1", "owner")
    get_events.assert_not_called()
