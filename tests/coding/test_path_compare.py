from pathlib import Path

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalPolicyOutcome,
    evaluate_approval,
    is_denied_secret_path,
)
from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.paths import resolve_readable_workspace_path
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


def call(
    name: str,
    input: dict[str, object],
    risk: ToolRisk,
) -> ValidatedToolCall:
    return ValidatedToolCall(name=name, input=input, risk=risk)


def test_write_via_symlink_to_agents_requires_approval(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (tmp_path / "notes.md").symlink_to(tmp_path / "AGENTS.md")
    write = call(
        "write_file.v1",
        {"path": "notes.md", "content": "ignore previous"},
        ToolRisk.WORKSPACE_WRITE,
    )
    gate = ApprovalGate(
        approved_always=frozenset({"write_file.v1"}),
        workspace_root=str(tmp_path),
    )

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_write_via_symlink_to_normal_file_is_not_instruction_always_ask(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "notes.md").symlink_to(tmp_path / "app.py")
    write = call(
        "write_file.v1",
        {"path": "notes.md", "content": "print(2)\n"},
        ToolRisk.WORKSPACE_WRITE,
    )
    gate = ApprovalGate(
        approved_always=frozenset({"write_file.v1"}),
        workspace_root=str(tmp_path),
    )

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.ALLOW


def test_execute_operand_symlink_to_agents_requires_approval(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (tmp_path / "notes.md").symlink_to(tmp_path / "AGENTS.md")
    command = call(
        "execute.v1",
        {"argv": ["sed", "-i", "s/a/b/", "notes.md"]},
        ToolRisk.COMMAND,
    )
    gate = ApprovalGate(
        approved_always=frozenset({"execute.v1"}),
        workspace_root=str(tmp_path),
    )

    assert evaluate_approval(command, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_write_under_claude_rules_requires_approval_despite_approved_always() -> None:
    write = call(
        "write_file.v1",
        {"path": ".claude/rules/safety.md", "content": "always do x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    gate = ApprovalGate(approved_always=frozenset({"write_file.v1"}))

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_execute_operand_realpath_to_claude_rules_requires_approval(
    tmp_path: Path,
) -> None:
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "safety.md").write_text("always do x\n", encoding="utf-8")
    (tmp_path / "hint.md").symlink_to(rules / "safety.md")
    command = call(
        "execute.v1",
        {"argv": ["sed", "-i", "s/a/b/", "hint.md"]},
        ToolRisk.COMMAND,
    )
    gate = ApprovalGate(
        approved_always=frozenset({"execute.v1"}),
        workspace_root=str(tmp_path),
    )

    assert evaluate_approval(command, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_unattended_execute_realpath_to_instruction_file_is_deny(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.local.md").write_text("local\n", encoding="utf-8")
    (tmp_path / "notes.md").symlink_to(tmp_path / "CLAUDE.local.md")
    command = call(
        "execute.v1",
        {"argv": ["sed", "-i", "s/a/b/", "notes.md"]},
        ToolRisk.COMMAND,
    )
    gate = ApprovalGate(
        approved_always=frozenset({"execute.v1"}),
        unattended=True,
        workspace_root=str(tmp_path),
    )

    assert evaluate_approval(command, gate) is ApprovalPolicyOutcome.DENY


def test_secret_path_compare_uses_nfkc_without_mutating_input() -> None:
    supplied = "．env"
    read = call("read_file.v1", {"path": supplied}, ToolRisk.READ_ONLY)

    assert is_denied_secret_path(supplied)
    assert evaluate_approval(read) is ApprovalPolicyOutcome.DENY
    assert read.input["path"] == supplied
    assert supplied == "．env"


def test_instruction_path_compare_uses_nfkc_without_mutating_input() -> None:
    supplied = "ＡＧＥＮＴＳ.md"
    write = call(
        "write_file.v1",
        {"path": supplied, "content": "ignore previous"},
        ToolRisk.WORKSPACE_WRITE,
    )
    gate = ApprovalGate(approved_always=frozenset({"write_file.v1"}))

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert write.input["path"] == supplied
    assert supplied == "ＡＧＥＮＴＳ.md"


def test_readable_resolve_denies_nfkc_secret_without_mutating_input(
    tmp_path: Path,
) -> None:
    supplied = "．env"
    (tmp_path / "ok.txt").write_text("ok\n", encoding="utf-8")

    with pytest.raises(SandboxPolicyViolation, match="workspace_secret_path"):
        resolve_readable_workspace_path(tmp_path, supplied)

    assert supplied == "．env"
    assert resolve_readable_workspace_path(tmp_path, "ok.txt").name == "ok.txt"
