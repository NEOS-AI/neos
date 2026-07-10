from unittest.mock import patch

import pytest

from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel, IntentType, WorkflowNode
from neos.workflow.routing import OrchestratorRouter

pytestmark = pytest.mark.no_db


def test_deep_analysis_settings_defaults():
    assert settings.DEEP_ANALYSIS_ENABLED is False
    assert settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD == 0.5


def test_deep_analysis_enum_values():
    assert WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value == "deep_analysis_orchestrator"
    assert IntentType.DEEP_ANALYSIS.value == "deep_analysis"


def _state(intent, complexity):
    return {
        "autonomy_level": AutonomyLevel.ASSISTED.value,
        "query_intent": intent,
        "query_classification": {"complexity_score": complexity},
        "required_agents": [],
        "selected_tools": [],
        "original_query": "심층 분석해줘",
    }


def test_routes_to_deep_analysis_when_enabled_and_intent_matches():
    state = _state(IntentType.DEEP_ANALYSIS.value, 0.1)

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = True
        mock_settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD = 0.5
        mock_settings.HYPER_DEEP_AGENT_ENABLED = False
        mock_settings.RECURSIVE_AGENT_ENABLED = False
        result = OrchestratorRouter().route(state)

    assert result == "deep_analysis"


def test_routes_to_deep_analysis_when_enabled_and_complexity_high():
    state = _state(IntentType.DEEP_RESEARCH.value, 0.9)

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = True
        mock_settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD = 0.5
        mock_settings.HYPER_DEEP_AGENT_ENABLED = False
        mock_settings.RECURSIVE_AGENT_ENABLED = False
        result = OrchestratorRouter().route(state)

    assert result == "deep_analysis"


def test_deep_analysis_takes_priority_over_hyper_deep_and_recursive():
    state = _state(IntentType.DEEP_RESEARCH.value, 0.99)

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = True
        mock_settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD = 0.5
        mock_settings.HYPER_DEEP_AGENT_ENABLED = True
        mock_settings.RECURSIVE_AGENT_ENABLED = True
        mock_settings.HYPER_DEEP_COMPLEXITY_THRESHOLD = 0.8
        mock_settings.RECURSIVE_COMPLEXITY_THRESHOLD = 0.7
        result = OrchestratorRouter().route(state)

    assert result == "deep_analysis"


def test_no_deep_analysis_when_disabled():
    state = _state(IntentType.DEEP_RESEARCH.value, 0.9)

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = False
        mock_settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD = 0.5
        mock_settings.HYPER_DEEP_AGENT_ENABLED = False
        mock_settings.RECURSIVE_AGENT_ENABLED = False
        result = OrchestratorRouter().route(state)

    assert result != "deep_analysis"


def test_no_deep_analysis_when_policy_disallows_recursive_research():
    state = _state(IntentType.DEEP_ANALYSIS.value, 0.9)
    state["autonomy_level"] = AutonomyLevel.MANUAL.value

    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = True
        mock_settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD = 0.5
        mock_settings.HYPER_DEEP_AGENT_ENABLED = False
        mock_settings.RECURSIVE_AGENT_ENABLED = False
        result = OrchestratorRouter().route(state)

    assert result != "deep_analysis"
