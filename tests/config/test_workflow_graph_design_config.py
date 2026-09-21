"""`graph_design_*` 설정 — 기본값이 계약이다.

`graph_design_model` 의 기본값 `None` 은 "역할 기본값으로 해석하라"는 뜻이며
(`deep_analysis.models.*` · `coding_model.model` · `recursive_agent.planner_model`
이 쓰는 것과 같은 계약), 문자열은 기능 오버라이드다.
"""

import pytest
from pydantic import ValidationError

from neos.config.schema import WorkflowConfig


def test_graph_design_model_defaults_to_none_meaning_role_default() -> None:
    assert WorkflowConfig().graph_design_model is None


def test_graph_design_budget_hint_has_a_default_matching_the_existing_tests() -> None:
    # 기존 테스트(`test_graph_designer_llm.py`)가 전부 1000 을 쓴다. 프로덕션
    # 기본값을 같게 두어 배선이 동작 차이를 만들지 않게 한다.
    assert WorkflowConfig().graph_design_budget_hint == 1000


def test_graph_design_enabled_stays_off_by_default() -> None:
    # 이 계획 전체의 Global Constraint. 켜는 것은 별도 결정이다.
    assert WorkflowConfig().graph_design_enabled is False


def test_subagent_node_flags_default_off() -> None:
    # 트랙 I GS-K9: 전부 기본 off, 예산은 지어내지 않는다.
    config = WorkflowConfig()
    assert config.subagent_nodes_enabled is False
    assert config.subagent_max_active == 1
    assert config.subagent_budget_micros is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"subagent_nodes_enabled": True},
        {"subagent_nodes_enabled": True, "graph_design_enabled": True},
        {"subagent_nodes_enabled": True, "subagent_budget_micros": 1_000},
    ],
)
def test_subagent_nodes_refuse_to_turn_on_without_design_and_budget(kwargs) -> None:
    with pytest.raises(ValidationError, match="subagent_nodes_enabled"):
        WorkflowConfig(**kwargs)


def test_subagent_nodes_turn_on_with_design_and_budget() -> None:
    config = WorkflowConfig(
        subagent_nodes_enabled=True, graph_design_enabled=True, subagent_budget_micros=1
    )
    assert config.subagent_nodes_enabled is True


@pytest.mark.parametrize("value", [0, 5])
def test_subagent_max_active_is_capped_at_four(value) -> None:
    with pytest.raises(ValidationError):
        WorkflowConfig(subagent_max_active=value)
