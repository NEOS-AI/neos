"""Q2: the user's own rules -- allow / require / block (design §2).

The order is fixed in code:

    USER_ONLY > base DENY > user block > protected-file REQUIRE > user require
    > operator allow > user allow (only the risk-default REQUIRE) > default

A user rule narrows anything; it widens only the one thing a person would
otherwise be asked about because of the call's risk class. Every case below
names the layer that must win.
"""

from __future__ import annotations

import pytest

from neos.coding.application.user_rules import parse_rule_fields
from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    UserApprovalRule,
    UserRuleEffect,
    adaptive_denial_reason,
    denial_envelope,
    evaluate_approval,
    policy_denial_reason,
    user_rule_matches,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db

ALLOW = ApprovalPolicyOutcome.ALLOW
DENY = ApprovalPolicyOutcome.DENY
REQUIRE = ApprovalPolicyOutcome.REQUIRE_APPROVAL


def run(*argv: str) -> ValidatedToolCall:
    return ValidatedToolCall("execute.v1", {"argv": list(argv)}, ToolRisk.COMMAND)


def write(path: str) -> ValidatedToolCall:
    return ValidatedToolCall(
        "write_file.v1", {"path": path, "content": "x"}, ToolRisk.WORKSPACE_WRITE
    )


READ = ValidatedToolCall("read_file.v1", {"path": "src/app.py"}, ToolRisk.READ_ONLY)


def rule(effect: str, tool: str = "execute.v1", *prefix: str) -> UserApprovalRule:
    return UserApprovalRule(f"ur_{effect}_{tool}", UserRuleEffect(effect), tool, prefix)


def gate(*rules: UserApprovalRule, **kwargs) -> ApprovalGate:
    return ApprovalGate(user_rules=tuple(rules), **kwargs)


# -- block ------------------------------------------------------------------------


def test_block_beats_every_allow_there_is() -> None:
    call = run("pytest", "-q")
    blocked = rule("block", "execute.v1", "pytest")

    assert evaluate_approval(call, gate(blocked)) is DENY
    assert evaluate_approval(call, gate(blocked, allow_tools=frozenset({"execute.v1"}))) is DENY
    assert evaluate_approval(
        call, gate(blocked, approved_always=frozenset({"execute.v1:pytest"}))
    ) is DENY
    assert evaluate_approval(
        call, gate(blocked, mode=ApprovalMode.AUTO, always_allow=frozenset({"execute.v1"}))
    ) is DENY
    assert evaluate_approval(call, gate(blocked, rule("allow", "execute.v1", "pytest"))) is DENY


def test_block_reaches_read_only_tools_too() -> None:
    assert evaluate_approval(READ, gate()) is ALLOW
    assert evaluate_approval(READ, gate(rule("block", "read_file.v1"))) is DENY


def test_a_block_has_its_own_reason_and_user_only_keeps_its_own() -> None:
    blocked = gate(rule("block", "execute.v1", "pytest"), rule("block", "execute.v1", "gh"))

    assert policy_denial_reason(run("pytest"), blocked) == "policy_user_rule_blocked"
    assert policy_denial_reason(run("gh", "auth", "login"), blocked) == "policy_user_only"
    assert policy_denial_reason(run("ruff"), blocked) == "policy_approval_denied"


def test_the_model_is_told_not_to_retry_a_blocked_call() -> None:
    envelope = denial_envelope(run("pytest"), "policy_user_rule_blocked")

    assert envelope["reason"] == adaptive_denial_reason("policy_user_rule_blocked")
    assert "do not retry" in envelope["reason"]
    assert envelope["denied_by"] == "policy"


# -- require ----------------------------------------------------------------------


def test_require_beats_the_operators_allow_and_remembered_approvals() -> None:
    call = run("pytest")
    required = rule("require", "execute.v1", "pytest")

    assert evaluate_approval(call, gate(required, allow_tools=frozenset({"execute.v1"}))) is REQUIRE
    assert evaluate_approval(
        call, gate(required, approved_always=frozenset({"execute.v1:pytest"}))
    ) is REQUIRE
    assert evaluate_approval(
        call, gate(required, mode=ApprovalMode.AUTO, always_allow=frozenset({"execute.v1"}))
    ) is REQUIRE
    assert evaluate_approval(READ, gate(rule("require", "read_file.v1"))) is REQUIRE


def test_require_beats_the_users_own_allow() -> None:
    both = gate(rule("require", "execute.v1", "pytest"), rule("allow", "execute.v1", "pytest"))

    assert evaluate_approval(run("pytest"), both) is REQUIRE


def test_require_with_nobody_watching_is_a_refusal() -> None:
    """Unattended folds REQUIRE to DENY (D-L1) -- a user require is no exception."""
    required = gate(rule("require", "execute.v1", "pytest"), unattended=True,
                    allow_tools=frozenset({"execute.v1"}))

    assert evaluate_approval(run("pytest"), required) is DENY


# -- allow ------------------------------------------------------------------------


def test_allow_lifts_only_the_risk_default() -> None:
    assert evaluate_approval(run("pytest"), gate()) is REQUIRE
    assert evaluate_approval(run("pytest"), gate(rule("allow", "execute.v1", "pytest"))) is ALLOW
    assert evaluate_approval(write("src/a.py"), gate(rule("allow", "write_file.v1"))) is ALLOW


@pytest.mark.parametrize(
    ("call", "extra"),
    [
        (run("gh", "auth", "login"), {}),                                   # USER_ONLY
        (run("pytest"), {"read_only_ceiling": True}),                       # background ceiling
        (write(".env"), {}),                                                # secret path
        (run("pytest"), {"deny_tools": frozenset({"execute.v1"})}),         # operator deny
    ],
)
def test_allow_never_lifts_a_base_denial(call, extra) -> None:
    allowed = gate(rule("allow", call.name), rule("allow", "execute.v1", "gh"), **extra)

    assert evaluate_approval(call, allowed) is DENY


@pytest.mark.parametrize("path", ["AGENTS.md", "CLAUDE.md", ".vscode/settings.json"])
def test_allow_never_lifts_a_protected_file_approval(path) -> None:
    assert evaluate_approval(write(path), gate(rule("allow", "write_file.v1"))) is REQUIRE


def test_allow_never_lifts_a_phase_change_approval() -> None:
    call = ValidatedToolCall("set_phase.v1", {"phase": "implement"}, ToolRisk.WORKSPACE_WRITE)
    phased = gate(rule("allow", "set_phase.v1"), current_phase="plan")

    assert evaluate_approval(call, gate(current_phase="plan")) is REQUIRE
    assert evaluate_approval(call, phased) is REQUIRE


def test_allow_with_nobody_watching_runs() -> None:
    """That is the point of an allow: an autonomous run need not stop for it."""
    allowed = gate(rule("allow", "execute.v1", "pytest"), unattended=True)

    assert evaluate_approval(run("pytest"), allowed) is ALLOW
    assert evaluate_approval(run("ruff"), allowed) is DENY


# -- matching ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "prefix", "expected"),
    [
        (("git", "push"), ("git", "push"), True),
        (("git", "push", "origin", "main"), ("git", "push"), True),
        (("git", "status"), ("git", "push"), False),
        (("git", "-C", "repo", "push"), ("git", "push"), True),
        (("env", "X=1", "timeout", "30", "git", "push"), ("git", "push"), True),
        (("git", "log", "push"), ("git", "push"), False),
        (("gitx", "push"), ("git",), False),
        (("pytest", "-q"), ("pytest",), True),
    ],
)
def test_argv_prefixes_match_like_the_user_only_floor(argv, prefix, expected) -> None:
    assert user_rule_matches(rule("block", "execute.v1", *prefix), run(*argv)) is expected


def test_a_rule_without_a_prefix_is_the_whole_tool() -> None:
    assert user_rule_matches(rule("block", "execute.v1"), run("anything"))
    assert not user_rule_matches(rule("block", "write_file.v1"), run("anything"))


def test_a_prefix_never_matches_another_tool_or_an_empty_argv() -> None:
    assert not user_rule_matches(rule("block", "read_file.v1", "x"), READ)
    # A hand-built rule (the parser refuses this shape) still cannot read argv off another tool.
    odd = ValidatedToolCall("read_file.v1", {"path": "a", "argv": ["x"]}, ToolRisk.READ_ONLY)
    assert not user_rule_matches(rule("block", "read_file.v1", "x"), odd)
    empty = ValidatedToolCall("execute.v1", {"argv": []}, ToolRisk.COMMAND)
    assert not user_rule_matches(rule("block", "execute.v1", "git"), empty)


def test_no_rules_is_todays_behaviour() -> None:
    for call in (run("pytest"), READ, write("src/a.py")):
        assert evaluate_approval(call, gate()) is evaluate_approval(call, ApprovalGate())


# -- parsing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("effect", "tool", "prefix"),
    [
        ("permit", "execute.v1", []),
        ("block", "", []),
        ("block", "has space", []),
        ("block", "write_file.v1", ["git"]),
        ("block", "execute.v1", ["--force"]),
        ("block", "execute.v1", [""]),
        ("block", "execute.v1", [" git"]),
        ("block", "execute.v1", ["a"] * 9),
        ("block", "execute.v1", [7]),
    ],
)
def test_malformed_rules_are_refused(effect, tool, prefix) -> None:
    with pytest.raises(ValueError):
        parse_rule_fields(effect, tool, prefix)


def test_a_well_formed_rule_parses() -> None:
    assert parse_rule_fields("block", " execute.v1 ", ["git", "push"]) == (
        UserRuleEffect.BLOCK, "execute.v1", ("git", "push")
    )
