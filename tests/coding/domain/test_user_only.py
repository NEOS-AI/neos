"""Q2: actions nobody can delegate to the agent -- not even with approval.

Roadmap track Q (docs/OPENAI_DOTS_ANALYSIS_260930.md §4.2 Q2, decision 2):
the list is fixed in code and config may only add to it. USER_ONLY is a
DENY-class outcome with its own reason code, not a fourth enum member --
`_approval_gate_step` executes anything that is neither DENY nor
REQUIRE_APPROVAL, so a new member would fail open.

Today the coding sandbox's validation already blocks most of these (the
executable allowlist defaults to pytest/ruff/mypy/pnpm/git). The floor is for
the day an operator widens `command_allowlist`: `gh` becomes runnable, and
`gh auth login` must still be the user's to run.
"""

from __future__ import annotations

import dataclasses

import pytest

from neos.coding.domain.approvals import (
    USER_ONLY_COMMANDS,
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    adaptive_denial_reason,
    evaluate_approval,
    policy_denial_reason,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


def run(*argv: str) -> ValidatedToolCall:
    return ValidatedToolCall("execute.v1", {"argv": list(argv)}, ToolRisk.COMMAND)


def test_the_floor_names_what_it_protects() -> None:
    """By name, not by count: a count does not say which entry went missing."""
    for entry in (
        ("gh", "auth"),
        ("gh", "secret"),
        ("gh", "repo", "delete"),
        ("gh", "repo", "edit"),
        ("docker", "login"),
        ("npm", "login"),
        ("npm", "token"),
        ("passwd",),
    ):
        assert entry in USER_ONLY_COMMANDS


def test_user_only_is_denied_even_when_every_allow_path_says_yes() -> None:
    """Auto mode, allow-listed, remembered: approval cannot delegate it."""
    gate = ApprovalGate(
        mode=ApprovalMode.AUTO,
        allow_tools=frozenset({"execute.v1"}),
        always_allow=frozenset({"execute.v1"}),
        approved_always=frozenset({"execute.v1:gh"}),
    )

    assert evaluate_approval(run("gh", "auth", "login"), gate) is ApprovalPolicyOutcome.DENY


def test_an_attended_user_only_call_is_not_offered_for_approval() -> None:
    """REQUIRE_APPROVAL would let a person click it through. USER_ONLY must not."""
    outcome = evaluate_approval(run("gh", "auth", "login"), ApprovalGate())

    assert outcome is ApprovalPolicyOutcome.DENY


def test_a_neighbouring_command_keeps_the_ordinary_policy() -> None:
    """`gh pr view` is not on the floor -- manual mode still asks."""
    outcome = evaluate_approval(run("gh", "pr", "view"), ApprovalGate())

    assert outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL


@pytest.mark.parametrize(
    "argv",
    [
        ("env", "GH_HOST=example.com", "gh", "auth", "login"),
        ("timeout", "30", "gh", "auth", "status"),
        ("gh", "--hostname", "example.com", "auth", "login"),
    ],
)
def test_wrappers_and_flags_do_not_hide_a_user_only_command(argv) -> None:
    assert evaluate_approval(run(*argv), ApprovalGate()) is ApprovalPolicyOutcome.DENY


@pytest.mark.parametrize(
    "argv",
    [
        ("gh", "authx"),
        ("gh", "pr", "view", "auth"),
        ("echo", "gh", "auth", "login"),
    ],
)
def test_prefix_tokens_must_line_up_with_the_command(argv) -> None:
    """Whole tokens, in order, right after the executable -- not anywhere."""
    assert evaluate_approval(run(*argv), ApprovalGate()) is not ApprovalPolicyOutcome.DENY


def test_config_can_add_to_the_floor() -> None:
    extra = frozenset({("gh", "workflow", "run")})

    before = evaluate_approval(run("gh", "workflow", "run", "deploy"), ApprovalGate())
    after = evaluate_approval(
        run("gh", "workflow", "run", "deploy"), ApprovalGate(user_only_extra=extra)
    )

    assert before is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert after is ApprovalPolicyOutcome.DENY


def test_the_gate_has_no_way_to_subtract_from_the_floor() -> None:
    """Decision 2: config only extends. No field may name a removal."""
    names = {field.name for field in dataclasses.fields(ApprovalGate)}

    assert "user_only_extra" in names
    assert not {n for n in names if "user_only" in n} - {"user_only_extra"}


def test_the_denial_reason_names_user_only() -> None:
    gate = ApprovalGate()

    assert policy_denial_reason(run("gh", "auth", "login"), gate) == "policy_user_only"
    assert policy_denial_reason(run("gh", "pr", "view"), gate) == "policy_approval_denied"


def test_the_model_is_told_to_hand_it_to_the_user() -> None:
    message = adaptive_denial_reason("policy_user_only")

    assert "user" in message
    assert "do not retry" in message
