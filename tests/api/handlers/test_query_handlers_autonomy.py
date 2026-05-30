import os
import json

import pytest
from fastapi import BackgroundTasks

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.handlers.query_handlers import process_query
from neos.api.models.query_models import QueryRequest


@pytest.mark.asyncio
async def test_query_preferences_autonomy_level_preserved_when_top_level_omitted(monkeypatch):
    captured = {}

    async def fake_get_or_create_user(user_id):
        return object()

    async def fake_process_query_workflow(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "response": "ok",
            "session_id": kwargs["session_id"],
            "metadata": {},
            "execution_time_ms": 1,
            "quality_score": 0.9,
            "errors": [],
        }

    monkeypatch.setattr(
        "neos.api.handlers.query_handlers.QueryService.get_or_create_user",
        fake_get_or_create_user,
    )
    monkeypatch.setattr(
        "neos.api.handlers.query_handlers.QueryService.process_query_workflow",
        fake_process_query_workflow,
    )

    await process_query(
        QueryRequest(query="hello", preferences={"autonomy_level": 2}),
        BackgroundTasks(),
    )

    assert captured["preferences"]["autonomy_level"] == 2


@pytest.mark.asyncio
async def test_query_preferences_accepts_null_preferences(monkeypatch):
    captured = {}

    async def fake_get_or_create_user(user_id):
        return object()

    async def fake_process_query_workflow(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "response": "ok",
            "session_id": kwargs["session_id"],
            "metadata": {},
            "execution_time_ms": 1,
            "quality_score": 0.9,
            "errors": [],
        }

    monkeypatch.setattr(
        "neos.api.handlers.query_handlers.QueryService.get_or_create_user",
        fake_get_or_create_user,
    )
    monkeypatch.setattr(
        "neos.api.handlers.query_handlers.QueryService.process_query_workflow",
        fake_process_query_workflow,
    )

    await process_query(
        QueryRequest(query="hello", preferences=None, autonomy_level=0),
        BackgroundTasks(),
    )

    assert captured["bypass_cache"] is False
    assert captured["preferences"]["autonomy_level"] == 0


@pytest.mark.asyncio
async def test_query_interrupted_result_returns_accepted_response(monkeypatch):
    async def fake_get_or_create_user(user_id):
        return object()

    async def fake_process_query_workflow(**kwargs):
        return {
            "success": True,
            "interrupted": True,
            "response": None,
            "session_id": kwargs["session_id"],
            "metadata": {},
            "execution_time_ms": 1,
            "quality_score": 0.0,
            "errors": [],
            "pending_approvals": [
                {"request_id": "approval_123", "skill_name": "realtime_info_search"}
            ],
        }

    monkeypatch.setattr(
        "neos.api.handlers.query_handlers.QueryService.get_or_create_user",
        fake_get_or_create_user,
    )
    monkeypatch.setattr(
        "neos.api.handlers.query_handlers.QueryService.process_query_workflow",
        fake_process_query_workflow,
    )

    response = await process_query(
        QueryRequest(query="hello", preferences={"autonomy_level": 0}),
        BackgroundTasks(),
    )

    assert response.status_code == 202
    body = json.loads(response.body)
    assert body["interrupted"] is True
    assert body["pending_approvals"][0]["skill_name"] == "realtime_info_search"
