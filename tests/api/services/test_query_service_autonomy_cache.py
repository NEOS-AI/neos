import os
from unittest.mock import AsyncMock

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services.query_service import QueryService


def test_query_cache_key_includes_autonomy_level():
    assisted = QueryService._generate_cache_key(
        user_id="user_123",
        query="What is the weather today?",
        autonomy_level=1,
    )
    manual = QueryService._generate_cache_key(
        user_id="user_123",
        query="What is the weather today?",
        autonomy_level=0,
    )
    assisted_equivalent = QueryService._generate_cache_key(
        user_id="user_123",
        query="  WHAT IS THE WEATHER TODAY?  ",
        autonomy_level=1,
    )

    assert assisted == assisted_equivalent
    assert assisted != manual


@pytest.mark.asyncio
async def test_process_query_workflow_returns_interrupted_result(monkeypatch):
    cache_get = AsyncMock(return_value=None)
    cache_set = AsyncMock()
    monkeypatch.setattr(
        "neos.api.services.query_service.cache_manager.get",
        cache_get,
    )
    monkeypatch.setattr(
        "neos.api.services.query_service.cache_manager.set",
        cache_set,
    )

    async def fake_execute(**kwargs):
        return {
            "success": True,
            "interrupted": True,
            "response": None,
            "pending_approvals": [
                {"request_id": "approval_123", "skill_name": "realtime_info_search"}
            ],
        }

    monkeypatch.setattr(
        "neos.api.services.workflow_service.WorkflowService.execute",
        fake_execute,
    )

    result = await QueryService.process_query_workflow(
        user_id="user_123",
        session_id="session_123",
        query="latest AI news",
        preferences={"autonomy_level": 0},
    )

    assert result["interrupted"] is True
    assert result["session_id"] == "session_123"
    assert result["pending_approvals"][0]["skill_name"] == "realtime_info_search"
    cache_set.assert_not_awaited()
