import os
import sys
import types
from unittest.mock import patch

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services.workflow_service import WorkflowService


def test_resolve_autonomy_level_uses_default_without_preferences():
    with patch("neos.api.services.workflow_service.settings") as mock_settings:
        mock_settings.DEFAULT_AUTONOMY_LEVEL = 1

        assert WorkflowService.resolve_autonomy_level(None) == 1


def test_resolve_autonomy_level_accepts_valid_request_value():
    assert WorkflowService.resolve_autonomy_level({"autonomy_level": 2}) == 2
    assert WorkflowService.resolve_autonomy_level({"autonomy_level": "0"}) == 0


def test_resolve_autonomy_level_falls_back_for_invalid_value():
    with patch("neos.api.services.workflow_service.settings") as mock_settings:
        mock_settings.DEFAULT_AUTONOMY_LEVEL = 2

        assert WorkflowService.resolve_autonomy_level({"autonomy_level": 4}) == 1
        assert WorkflowService.resolve_autonomy_level({"autonomy_level": "bad"}) == 1


@pytest.mark.asyncio
async def test_execute_passes_bypass_cache_to_workflow(monkeypatch):
    captured = {}

    async def fake_execute_workflow(user_input, **kwargs):
        captured.update(user_input)
        return {"success": True, "response": "ok"}

    fake_graph_module = types.SimpleNamespace(
        multi_agent_workflow=types.SimpleNamespace(
            execute_workflow=fake_execute_workflow,
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "neos.workflow.graph",
        fake_graph_module,
    )

    await WorkflowService.execute(
        user_id="user_123",
        session_id="session_123",
        query="hello",
        preferences={"autonomy_level": 1},
        bypass_cache=True,
    )

    assert captured["bypass_cache"] is True


@pytest.mark.asyncio
async def test_execute_passes_mission_preferences_to_workflow(monkeypatch):
    captured = {}

    async def fake_execute_workflow(user_input, **kwargs):
        captured.update(user_input)
        return {"success": True, "response": "ok"}

    fake_graph_module = types.SimpleNamespace(
        multi_agent_workflow=types.SimpleNamespace(
            execute_workflow=fake_execute_workflow,
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "neos.workflow.graph",
        fake_graph_module,
    )

    await WorkflowService.execute(
        user_id="user_123",
        session_id="session_123",
        query="hello",
        preferences={
            "autonomy_level": 1,
            "use_mission_runtime": True,
            "mission_detail_level": "standard",
        },
    )

    assert captured["preferences"]["use_mission_runtime"] is True
    assert captured["preferences"]["mission_detail_level"] == "standard"
