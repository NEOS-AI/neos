from neos.workflow.thinking_strategy import (
    BranchPolicy,
    ProblemType,
    build_thinking_strategy,
)


def test_convergent_low_complexity_uses_single_path():
    strategy = build_thinking_strategy(
        intent="information_seeking",
        complexity_score=0.2,
        metadata={},
    )

    assert strategy.problem_type == ProblemType.CONVERGENT
    assert strategy.branch_policy == BranchPolicy.SINGLE_PATH
    assert strategy.effort_budget_tokens == 300
    assert strategy.requires_gate is False


def test_freshness_sensitive_research_requires_gate():
    strategy = build_thinking_strategy(
        intent="deep_research",
        complexity_score=0.82,
        metadata={"freshness_required": True},
    )

    assert strategy.problem_type == ProblemType.EXPLORATORY
    assert strategy.branch_policy == BranchPolicy.BOUNDED_BRANCHING
    assert strategy.effort_budget_tokens == 2000
    assert strategy.requires_gate is True
    assert strategy.max_branches == 3


def test_structural_request_uses_planning_budget():
    strategy = build_thinking_strategy(
        intent="technical_analysis",
        complexity_score=0.72,
        metadata={"request_kind": "architecture"},
    )

    assert strategy.problem_type == ProblemType.STRUCTURAL
    assert strategy.branch_policy == BranchPolicy.PLAN_THEN_EXECUTE
    assert strategy.effort_budget_tokens == 1200
