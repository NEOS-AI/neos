"""스펙 §4 — 엔진 재배치. 유형 기반 단일 디스패치 (AC1·AC2·AC4·AC5).

R1(임계값 역전): 세 블록이 같은 intent를 두고 경쟁해 뒤 두 엔진의 complexity
경로가 100% 도달 불가였다. 재배치 후 각 엔진은 자기 유형 intent로 항상 도달
가능해야 한다.
"""

import inspect
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from neos.workflow.enums import AutonomyLevel, IntentType, WorkflowPathway
from neos.workflow.routing import OrchestratorRouter
from neos.workflow.routing.orchestrator_router import _DEEP_ENGINES

pytestmark = pytest.mark.no_db

# 실제 스키마 기본값(neos/config/schema.py) — 임계값 역전을 그대로 재현한다.
_REAL_THRESHOLDS = {
    "DEEP_ANALYSIS_COMPLEXITY_THRESHOLD": 0.5,
    "HYPER_DEEP_COMPLEXITY_THRESHOLD": 0.85,
    "RECURSIVE_COMPLEXITY_THRESHOLD": 0.8,
}


def _state(intent, complexity=0.9):
    return {
        "autonomy_level": AutonomyLevel.ASSISTED.value,
        "query_intent": intent,
        "query_classification": {"complexity_score": complexity},
        "required_agents": [],
        "selected_tools": [],
        "original_query": "테스트 질의",
    }


@contextmanager
def _engines(*, deep_analysis=True, hyper_deep=True, recursive=True):
    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = deep_analysis
        mock_settings.HYPER_DEEP_AGENT_ENABLED = hyper_deep
        mock_settings.RECURSIVE_AGENT_ENABLED = recursive
        for attr, value in _REAL_THRESHOLDS.items():
            setattr(mock_settings, attr, value)
        yield mock_settings


# ── AC1 + AC4: 세 엔진 모두 활성일 때 각 엔진에 도달하는 질의가 존재한다 ──


def test_every_engine_is_reachable_when_all_three_are_enabled():
    """AC1·AC4. 임계값 역전(0.5 < 0.8 < 0.85)이 그대로여도 셋 다 도달 가능해야 한다."""
    reached = {}
    for engine in _DEEP_ENGINES:
        with _engines():
            reached[engine.name] = OrchestratorRouter().route(_state(engine.intent))

    assert reached == {engine.name: engine.name for engine in _DEEP_ENGINES}
    assert set(reached) == {"deep_analysis", "hyper_deep", "recursive"}


def test_no_engine_branch_is_unreachable_via_generic_fallback():
    """AC4. 레거시 generic intent의 fallback 경로도 엔진마다 도달 가능해야 한다."""
    with _engines(deep_analysis=True, hyper_deep=True, recursive=True):
        assert OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value)) == "deep_analysis"
    with _engines(deep_analysis=False, hyper_deep=True, recursive=True):
        assert OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value)) == "hyper_deep"
    with _engines(deep_analysis=False, hyper_deep=False, recursive=True):
        assert OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value)) == "recursive"


def test_explicit_type_intent_beats_generic_priority():
    """R1 해소의 핵심: deep_analysis가 1순위여도 유형 intent는 자기 엔진에 간다."""
    with _engines():
        assert OrchestratorRouter().route(_state(IntentType.HYPER_DEEP_RESEARCH.value)) == "hyper_deep"
        assert OrchestratorRouter().route(_state(IntentType.RECURSIVE_RESEARCH.value)) == "recursive"


def test_type_intent_ignores_complexity_gate():
    """스펙 §4.3-3: complexity는 '엔진을 쓸지'의 게이트일 뿐, 유형이 엔진을 정한다.
    유형을 명시한 질의는 낮은 complexity에서도 자기 엔진에 도달한다."""
    with _engines():
        assert OrchestratorRouter().route(_state(IntentType.HYPER_DEEP_RESEARCH.value, 0.0)) == "hyper_deep"


def test_disabled_engine_with_its_type_intent_falls_back_to_base_route():
    with _engines(hyper_deep=False):
        result = OrchestratorRouter().route(_state(IntentType.HYPER_DEEP_RESEARCH.value))
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


def test_generic_intent_below_gate_does_not_take_any_engine():
    with _engines():
        result = OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value, 0.1))
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


# ── AC2: 동일 구조 반복 블록이 남지 않는다 ────────────────────────────


def test_route_has_no_per_engine_repeated_blocks():
    """AC2. 엔진별 지식은 _DEEP_ENGINES 테이블에만 있어야 한다 — 분기 코드가
    엔진 수만큼 늘어나면 R1(임계값 역전)이 재발한다."""
    source = inspect.getsource(OrchestratorRouter.route)
    source += inspect.getsource(OrchestratorRouter.select_deep_engine)

    for flag in ("DEEP_ANALYSIS_ENABLED", "HYPER_DEEP_AGENT_ENABLED", "RECURSIVE_AGENT_ENABLED"):
        assert flag not in source, f"{flag}가 분기 코드에 하드코딩됐다"
    for threshold in (
        "DEEP_ANALYSIS_COMPLEXITY_THRESHOLD",
        "HYPER_DEEP_COMPLEXITY_THRESHOLD",
        "RECURSIVE_COMPLEXITY_THRESHOLD",
    ):
        assert threshold not in source, f"{threshold}가 분기 코드에 하드코딩됐다"
    for name in ('"deep_analysis"', '"hyper_deep"', '"recursive"'):
        assert name not in source, f"{name}가 분기 코드에 하드코딩됐다"


def test_engine_table_covers_three_engines_and_is_consistent():
    assert [e.name for e in _DEEP_ENGINES] == ["deep_analysis", "hyper_deep", "recursive"]
    assert [e.intent for e in _DEEP_ENGINES] == [
        IntentType.DEEP_ANALYSIS.value,
        IntentType.HYPER_DEEP_RESEARCH.value,
        IntentType.RECURSIVE_RESEARCH.value,
    ]


# ── AC5: 세 엔진 모두 비활성일 때 무회귀 ──────────────────────────────


@pytest.mark.parametrize(
    "intent",
    [
        IntentType.DEEP_ANALYSIS.value,
        IntentType.HYPER_DEEP_RESEARCH.value,
        IntentType.RECURSIVE_RESEARCH.value,
        IntentType.DEEP_RESEARCH.value,
        IntentType.COMPLEX_ANALYSIS.value,
    ],
)
def test_no_regression_when_all_engines_disabled(intent):
    with _engines(deep_analysis=False, hyper_deep=False, recursive=False):
        result = OrchestratorRouter().route(_state(intent))

    assert result not in {"deep_analysis", "hyper_deep", "recursive"}
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


def test_manual_autonomy_blocks_all_engines():
    state = _state(IntentType.DEEP_ANALYSIS.value)
    state["autonomy_level"] = AutonomyLevel.MANUAL.value

    with _engines():
        result = OrchestratorRouter().route(state)

    assert result not in {"deep_analysis", "hyper_deep", "recursive"}
