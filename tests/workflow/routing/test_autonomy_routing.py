import os
from unittest.mock import patch

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.workflow.enums import AutonomyLevel, IntentType, WorkflowPathway
from neos.workflow.routing import OrchestratorRouter, QualityRouter


def test_manual_autonomy_blocks_hyper_deep_route():
    state = {
        "autonomy_level": AutonomyLevel.MANUAL.value,
        "query_intent": IntentType.HYPER_DEEP_RESEARCH.value,
        "query_classification": {"complexity_score": 0.99},
        "required_agents": [],
        "selected_tools": [],
        "original_query": "AI 산업을 심층 조사해줘",
    }

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = False
        mock_settings.HYPER_DEEP_AGENT_ENABLED = True
        mock_settings.RECURSIVE_AGENT_ENABLED = True
        mock_settings.HYPER_DEEP_COMPLEXITY_THRESHOLD = 0.8
        mock_settings.RECURSIVE_COMPLEXITY_THRESHOLD = 0.7
        result = OrchestratorRouter().route(state)

    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


def test_assisted_autonomy_allows_hyper_deep_route():
    state = {
        "autonomy_level": AutonomyLevel.ASSISTED.value,
        "query_intent": IntentType.HYPER_DEEP_RESEARCH.value,
        "query_classification": {"complexity_score": 0.99},
        "required_agents": [],
        "selected_tools": [],
        "original_query": "AI 산업을 심층 조사해줘",
    }

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = False
        mock_settings.HYPER_DEEP_AGENT_ENABLED = True
        mock_settings.RECURSIVE_AGENT_ENABLED = True
        mock_settings.HYPER_DEEP_COMPLEXITY_THRESHOLD = 0.8
        mock_settings.RECURSIVE_COMPLEXITY_THRESHOLD = 0.7
        result = OrchestratorRouter().route(state)

    assert result == "hyper_deep"


def test_pending_approval_routes_before_orchestrators():
    state = {
        "autonomy_level": AutonomyLevel.AUTONOMOUS.value,
        "query_intent": IntentType.SIMPLE.value,
        "query_classification": {"complexity_score": 0.1},
        "required_agents": [],
        "selected_tools": [],
        "pending_approvals": [{"request_id": "approval-1"}],
        "approval_decision": None,
        "original_query": "hello",
    }

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = True
        mock_settings.DEEP_ANALYSIS_ENABLED = False
        mock_settings.HYPER_DEEP_AGENT_ENABLED = True
        mock_settings.RECURSIVE_AGENT_ENABLED = True
        result = OrchestratorRouter().route(state)

    assert result == "needs_approval"


def test_manual_autonomy_skips_adaptive_replan():
    state = {
        "autonomy_level": AutonomyLevel.MANUAL.value,
        "query_classification": {"sub_topics": ["a", "b"]},
        "search_results": [],
        "replan_count": 0,
    }

    assert QualityRouter().should_replan(state) == "skip_replan"
