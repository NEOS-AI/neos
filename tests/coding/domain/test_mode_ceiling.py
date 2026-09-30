"""Q1: a background task sees only what cannot change anything.

Roadmap track Q (docs/OPENAI_DOTS_ANALYSIS_260930.md §4.2 Q1): the dots
"proactive research" mode. Nobody asked for this work and nobody is watching,
so the ceiling is the *validated* risk READ_ONLY. Children need no rule of
their own: validation raises `spawn_agent.v1 spec=implement` to
WORKSPACE_WRITE, and an explore child's port refuses writes.
"""

from __future__ import annotations

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    evaluate_approval,
    policy_denial_reason,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db

CEILING = ApprovalGate(read_only_ceiling=True, unattended=True)


def tool(name: str, risk: ToolRisk, **input: object) -> ValidatedToolCall:
    return ValidatedToolCall(name, input, risk)


@pytest.mark.parametrize(
    "call",
    [
        tool("write_file.v1", ToolRisk.WORKSPACE_WRITE, path="a.py", content="x"),
        tool("execute.v1", ToolRisk.COMMAND, argv=["pytest"]),
        tool("ask_user.v1", ToolRisk.USER_QUESTION, questions=["?"]),
        tool("spawn_agent.v1", ToolRisk.WORKSPACE_WRITE, spec="implement"),
    ],
)
def test_the_ceiling_refuses_anything_that_can_change_something(call) -> None:
    assert evaluate_approval(call, CEILING) is ApprovalPolicyOutcome.DENY
    assert policy_denial_reason(call, CEILING) == "policy_mode_ceiling"


def test_reads_pass_under_the_ceiling() -> None:
    call = tool("read_file.v1", ToolRisk.READ_ONLY, path="a.py")

    assert evaluate_approval(call, CEILING) is ApprovalPolicyOutcome.ALLOW


def test_no_allow_path_lifts_the_ceiling() -> None:
    """Auto mode and allow lists are the operator's; the ceiling is the mode's."""
    gate = ApprovalGate(
        mode=ApprovalMode.AUTO,
        allow_tools=frozenset({"write_file.v1"}),
        always_allow=frozenset({"write_file.v1"}),
        read_only_ceiling=True,
    )
    call = tool("write_file.v1", ToolRisk.WORKSPACE_WRITE, path="a.py", content="x")

    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.DENY


def test_user_only_names_itself_even_under_the_ceiling() -> None:
    """FB1 (one hit) is stricter than FB2 (two); the stricter name wins."""
    call = tool("execute.v1", ToolRisk.COMMAND, argv=["gh", "auth", "login"])

    assert policy_denial_reason(call, CEILING) == "policy_user_only"


def test_a_read_only_explore_child_may_start_under_the_ceiling() -> None:
    """Proactive research may fan out to readers; it may not fan out to writers."""
    call = tool("spawn_agent.v1", ToolRisk.READ_ONLY, spec="explore")

    assert evaluate_approval(call, CEILING) is ApprovalPolicyOutcome.ALLOW
