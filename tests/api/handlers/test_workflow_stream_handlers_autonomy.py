import json
import os
from types import SimpleNamespace

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.handlers.workflow_stream_handlers import stream_query
from neos.api.models.query_models import WorkflowStreamRequest


class _FakeRequest:
    headers = {}


@pytest.mark.asyncio
async def test_stream_query_uses_body_preferences_for_bypass_cache(monkeypatch):
    captured = {}

    async def fake_execute_workflow_with_streaming(**kwargs):
        captured.update(kwargs)
        await kwargs["callback"].on_workflow_complete(
            {
                "success": True,
                "response": "ok",
                "metadata": {},
                "execution_time_ms": 1,
                "quality_score": 0.9,
                "errors": [],
            }
        )
        return captured

    monkeypatch.setattr(
        "neos.api.handlers.workflow_stream_handlers.execute_workflow_with_streaming",
        fake_execute_workflow_with_streaming,
    )

    response = await stream_query(
        WorkflowStreamRequest(
            query="hello",
            user_id="user_123",
            session_id="session_123",
            preferences={"bypass_cache": True, "use_mission_runtime": True},
            autonomy_level=2,
            stream_options={
                "include_heartbeat": False,
                "enable_db_logging": False,
            },
        ),
        _FakeRequest(),
        current_user=SimpleNamespace(user_id="user_123", is_active=True),
    )

    payloads = []
    async for chunk in response.body_iterator:
        payload = chunk.removeprefix("data: ").strip()
        payloads.append(json.loads(payload))
        if payloads[-1]["event"] == "completed":
            break

    assert captured["bypass_cache"] is True
    assert captured["autonomy_level"] == 2
    assert captured["workflow_preferences"]["use_mission_runtime"] is True
    assert payloads[-1]["event"] == "completed"
