from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ProblemType(str, Enum):
    CONVERGENT = "convergent"
    DIVERGENT = "divergent"
    EXPLORATORY = "exploratory"
    STRUCTURAL = "structural"


class BranchPolicy(str, Enum):
    SINGLE_PATH = "single_path"
    BOUNDED_BRANCHING = "bounded_branching"
    PLAN_THEN_EXECUTE = "plan_then_execute"


@dataclass(frozen=True)
class ThinkingStrategy:
    problem_type: ProblemType
    branch_policy: BranchPolicy
    effort_budget_tokens: int
    max_branches: int
    requires_gate: bool
    reason: str

    def to_state(self) -> dict[str, Any]:
        data = asdict(self)
        data["problem_type"] = self.problem_type.value
        data["branch_policy"] = self.branch_policy.value
        return data


def build_thinking_strategy(
    *,
    intent: str | None,
    complexity_score: float | None,
    metadata: dict[str, Any] | None = None,
) -> ThinkingStrategy:
    metadata = metadata or {}
    normalized_intent = (intent or "").lower()
    score = float(complexity_score or 0.0)
    freshness_required = bool(metadata.get("freshness_required"))
    request_kind = str(metadata.get("request_kind") or "").lower()

    if request_kind in {"architecture", "refactor", "system_design"}:
        return ThinkingStrategy(
            problem_type=ProblemType.STRUCTURAL,
            branch_policy=BranchPolicy.PLAN_THEN_EXECUTE,
            effort_budget_tokens=1200,
            max_branches=2,
            requires_gate=score >= 0.6,
            reason="structural_request",
        )

    if normalized_intent in {
        "deep_research",
        "hyper_deep_research",
        "recursive_research",
    }:
        return ThinkingStrategy(
            problem_type=ProblemType.EXPLORATORY,
            branch_policy=BranchPolicy.BOUNDED_BRANCHING,
            effort_budget_tokens=2000 if score >= 0.75 else 1200,
            max_branches=3,
            requires_gate=True,
            reason="research_intent",
        )

    if normalized_intent in {
        "comparison",
        "complex_analysis",
        "financial_analysis",
    }:
        return ThinkingStrategy(
            problem_type=ProblemType.DIVERGENT,
            branch_policy=BranchPolicy.BOUNDED_BRANCHING,
            effort_budget_tokens=1200 if score >= 0.6 else 800,
            max_branches=2,
            requires_gate=score >= 0.65 or freshness_required,
            reason="divergent_analysis",
        )

    if freshness_required or score >= 0.8:
        return ThinkingStrategy(
            problem_type=ProblemType.EXPLORATORY,
            branch_policy=BranchPolicy.BOUNDED_BRANCHING,
            effort_budget_tokens=1200,
            max_branches=2,
            requires_gate=True,
            reason="fresh_or_high_complexity",
        )

    return ThinkingStrategy(
        problem_type=ProblemType.CONVERGENT,
        branch_policy=BranchPolicy.SINGLE_PATH,
        effort_budget_tokens=300,
        max_branches=1,
        requires_gate=False,
        reason="default_convergent",
    )
