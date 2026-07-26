from unittest.mock import patch

import pytest

from neos.config.model_routing import resolve_model
from neos.config.schema import (
    DeepAnalysisModelsConfig,
    ModelRoutingConfig,
    RecursiveAgentConfig,
)
from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel, IntentType, WorkflowNode, WorkflowPathway
from neos.workflow.recursive.planner import RecursivePlanner
from neos.workflow.routing import OrchestratorRouter

pytestmark = pytest.mark.no_db


def test_deep_analysis_settings_defaults():
    """스키마 기본값은 off다.

    배포 값은 `config/neos.default.yaml`이 정하므로 여기서 런타임 설정을
    단언하면 안 된다 -- 플래그를 켜는 순간 이 테스트가 깨지고, 정작 검증하려던
    "코드 기본값" 계약은 확인하지 못한다.
    """
    from neos.config.schema import DeepAnalysisConfig

    defaults = DeepAnalysisConfig()
    assert defaults.enabled is False
    assert defaults.complexity_threshold == 0.5


@pytest.mark.parametrize(
    ("field", "role", "expected"),
    [
        ("scout", "everyday", "claude-sonnet-5"),
        ("dig", "powerful", "claude-opus-5"),
        ("synth", "powerful", "claude-opus-5"),
        ("judge", "everyday", "claude-sonnet-5"),
    ],
)
def test_deep_analysis_models_use_role_defaults(
    field, role, expected
) -> None:
    models = DeepAnalysisModelsConfig()

    assert getattr(models, field) is None
    assert (
        resolve_model(
            config=ModelRoutingConfig(),
            provider="anthropic",
            role=role,
            feature_override=getattr(models, field),
        ).model
        == expected
    )


@pytest.mark.parametrize(
    ("field", "role"),
    [
        ("scout", "everyday"),
        ("dig", "powerful"),
        ("synth", "powerful"),
        ("judge", "everyday"),
    ],
)
def test_deep_analysis_feature_models_win_over_roles(field, role) -> None:
    models = DeepAnalysisModelsConfig.model_validate({field: "claude-manual"})

    assert (
        resolve_model(
            config=ModelRoutingConfig(),
            provider="anthropic",
            role=role,
            feature_override=getattr(models, field),
        ).model
        == "claude-manual"
    )


def test_recursive_planner_uses_powerful_role_without_feature_override() -> None:
    recursive = RecursiveAgentConfig()

    assert recursive.planner_model is None
    assert (
        resolve_model(
            config=ModelRoutingConfig(),
            provider="anthropic",
            role="powerful",
            feature_override=recursive.planner_model,
        ).model
        == "claude-opus-5"
    )


def test_explicit_recursive_planner_model_wins_over_powerful_role() -> None:
    recursive = RecursiveAgentConfig(planner_model="claude-manual")

    assert (
        resolve_model(
            config=ModelRoutingConfig(),
            provider="anthropic",
            role="powerful",
            feature_override=recursive.planner_model,
        ).model
        == "claude-manual"
    )


@pytest.mark.parametrize(
    ("feature_model", "expected_model"),
    [
        (None, "claude-opus-5"),
        ("claude-manual", "claude-manual"),
    ],
)
def test_recursive_planner_resolves_model_at_consumer_boundary(
    monkeypatch, feature_model, expected_model
) -> None:
    monkeypatch.setattr(
        settings.config.recursive_agent,
        "planner_model",
        feature_model,
    )
    planner = object.__new__(RecursivePlanner)

    assert planner._select_model(0) == expected_model


def test_recursive_planner_lower_depth_keeps_configured_atomizer() -> None:
    planner = RecursivePlanner()

    assert planner._select_model(1) == settings.RECURSIVE_ATOMIZER_MODEL


def test_deep_analysis_enum_values():
    assert WorkflowNode.DEEP_ANALYSIS_DISPATCH.value == "deep_analysis_dispatch"
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
    # 다른 확장 오케스트레이터도 전부 비활성이므로 deep_analysis 도입 이전과 동일하게
    # base_route()의 use_orchestrators로 떨어져야 한다(deep_research는 _ALWAYS_SEARCH_INTENTS).
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


def test_no_regression_deep_analysis_off_by_default():
    """D18 무회귀 계약: DEEP_ANALYSIS_ENABLED가 기본값(False)일 때 deep_research/고복잡도
    쿼리는 하네스("deep_analysis")로 라우팅되지 않고, 하네스 도입 이전과 동일한
    recursive/hyper_deep/base 경로로 간다. 여기서는 recursive/hyper_deep도 비활성인
    구성으로 base_route(use_orchestrators)에 떨어짐을 명시적으로 고정한다."""
    # 배포 값(config/neos.default.yaml)에 의존하지 않는다 -- 아래에서 플래그를
    # 명시적으로 끄고 그 경로를 검증한다.
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
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


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
