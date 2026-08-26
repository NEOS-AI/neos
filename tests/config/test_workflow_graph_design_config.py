"""`graph_design_*` 설정 — 기본값이 계약이다.

`graph_design_model` 의 기본값 `None` 은 "역할 기본값으로 해석하라"는 뜻이며
(`deep_analysis.models.*` · `coding_model.model` · `recursive_agent.planner_model`
이 쓰는 것과 같은 계약), 문자열은 기능 오버라이드다.
"""

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
