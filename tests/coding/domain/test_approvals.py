import json

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    ApprovalStatus,
    approval_display_summary,
    canonical_approval_hash,
    evaluate_approval,
    requires_approval_answers,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall


def call(
    name: str,
    input: dict[str, object],
    risk: ToolRisk,
) -> ValidatedToolCall:
    return ValidatedToolCall(name=name, input=input, risk=risk)


def binding(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "ct_1",
        "run_id": "cr_1",
        "tool_call_id": "tool_1",
        "tool_name": "write_file.v1",
        "normalized_input": {"path": "src/main.py", "content": "value"},
        "checkpoint_id": "cc_1",
        "workspace_revision": "rev-1",
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        "svc/.env",
        "svc/.env.staging",
        ".git",
        ".git/config",
        ".git/HEAD",
        ".git/credentials",
        "pkg/.git/config",
        "pkg/.git/credentials",
        ".ssh/id_ed25519",
        "home/.ssh/config",
        "id_rsa",
        "keys/id_rsa",
        ".aws/credentials",
        "svc/.aws/credentials",
    ],
)
def test_secret_dotfile_paths_are_denied_even_when_read_only(path: str) -> None:
    read = call("read_file.v1", {"path": path}, ToolRisk.READ_ONLY)
    write = call(
        "write_file.v1",
        {"path": path, "content": "secret"},
        ToolRisk.WORKSPACE_WRITE,
    )
    auto_read = evaluate_approval(
        read,
        ApprovalGate(
            mode=ApprovalMode.AUTO,
            always_allow=frozenset({"read_file.v1"}),
        ),
    )
    approved_write = evaluate_approval(
        write,
        ApprovalGate(approved_always=frozenset({"write_file.v1"})),
    )

    assert evaluate_approval(read) is ApprovalPolicyOutcome.DENY
    assert evaluate_approval(write) is ApprovalPolicyOutcome.DENY
    assert auto_read is ApprovalPolicyOutcome.DENY
    assert approved_write is ApprovalPolicyOutcome.DENY


def test_search_text_paths_are_denied_when_they_target_secrets() -> None:
    search = call(
        "search_text.v1",
        {"query": "TOKEN", "paths": [".env", "src"]},
        ToolRisk.READ_ONLY,
    )
    assert evaluate_approval(search) is ApprovalPolicyOutcome.DENY


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "src/main.py",
        ".gitignore",
        ".envrc",
        "id_rsa.pub",
        ".aws/config",
        ".github/workflows/ci.yml",
    ],
)
def test_non_secret_paths_keep_existing_approval_policy(path: str) -> None:
    read = call("read_file.v1", {"path": path}, ToolRisk.READ_ONLY)
    write = call(
        "write_file.v1",
        {"path": path, "content": "value"},
        ToolRisk.WORKSPACE_WRITE,
    )

    assert evaluate_approval(read) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(write) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_policy_allows_reads_and_requires_exact_approval_for_mutations() -> None:
    read = call("read_file.v1", {"path": "README.md"}, ToolRisk.READ_ONLY)
    write = call(
        "write_file.v1",
        {"path": "src/main.py", "content": "value"},
        ToolRisk.WORKSPACE_WRITE,
    )
    command = call("execute.v1", {"argv": ["pytest"]}, ToolRisk.COMMAND)
    lint = call("execute.v1", {"argv": ["ruff", "check"]}, ToolRisk.COMMAND)

    assert evaluate_approval(read) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(write) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(command) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(lint) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_approval_gate_denies_listed_tools_and_fail_closes() -> None:
    write = call(
        "write_file.v1",
        {"path": "src/main.py", "content": "value"},
        ToolRisk.WORKSPACE_WRITE,
    )
    denied = evaluate_approval(
        write, ApprovalGate(deny_tools=frozenset({"write_file.v1"}))
    )
    auto_allow = evaluate_approval(
        write,
        ApprovalGate(
            mode=ApprovalMode.AUTO,
            always_allow=frozenset({"write_file.v1"}),
        ),
    )
    manual_seed = evaluate_approval(
        write,
        ApprovalGate(
            mode=ApprovalMode.MANUAL,
            always_allow=frozenset({"write_file.v1"}),
        ),
    )
    assert denied is ApprovalPolicyOutcome.DENY
    assert auto_allow is ApprovalPolicyOutcome.ALLOW
    assert manual_seed is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_approved_always_allows_named_workspace_writes_only() -> None:
    write = call(
        "write_file.v1",
        {"path": "src/main.py", "content": "value"},
        ToolRisk.WORKSPACE_WRITE,
    )
    edit = call(
        "edit_file.v1",
        {"path": "src/main.py", "old_string": "a", "new_string": "b"},
        ToolRisk.WORKSPACE_WRITE,
    )
    command = call("execute.v1", {"argv": ["pytest"]}, ToolRisk.COMMAND)
    gate = ApprovalGate(approved_always=frozenset({"write_file.v1"}))

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(edit, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(command, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_set_phase_to_implement_from_plan_requires_approval() -> None:
    jump = call("set_phase.v1", {"phase": "implement"}, ToolRisk.READ_ONLY)
    assert (
        evaluate_approval(jump, ApprovalGate(current_phase="plan"))
        is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    )
    assert (
        evaluate_approval(jump, ApprovalGate(current_phase="implement"))
        is ApprovalPolicyOutcome.ALLOW
    )
    assert requires_approval_answers("ask_user.v1")
    assert not requires_approval_answers("write_file.v1")


def test_canonical_hash_is_deterministic_and_binding_sensitive() -> None:
    first = canonical_approval_hash(binding())
    reordered = canonical_approval_hash(dict(reversed(tuple(binding().items()))))

    assert first == reordered
    assert first != canonical_approval_hash(binding(workspace_revision="rev-2"))
    assert first != canonical_approval_hash(
        binding(normalized_input={"path": "src/main.py", "content": "other"})
    )
    assert len(first) == 64


def test_write_summary_exposes_path_but_never_content() -> None:
    summary = approval_display_summary(
        call(
            "write_file.v1",
            {"path": "src/main.py", "content": "raw-secret-content"},
            ToolRisk.WORKSPACE_WRITE,
        )
    )

    encoded = json.dumps(summary)
    assert summary == {"path": "src/main.py"}
    assert "raw-secret-content" not in encoded


def test_command_summary_exposes_executable_and_count_but_not_values() -> None:
    summary = approval_display_summary(
        call(
            "execute.v1",
            {
                "argv": ["pytest", "tests/private_test.py", "-q"],
                "env": {"TOKEN": "raw-secret-token"},
                "stdin": "raw-secret-stdin",
                "cwd": ".",
            },
            ToolRisk.COMMAND,
        )
    )

    encoded = json.dumps(summary)
    assert summary == {"executable": "pytest", "argument_count": 2}
    assert "warnings" not in summary
    assert "private_test.py" not in encoded
    assert "raw-secret-token" not in encoded
    assert "raw-secret-stdin" not in encoded


def test_command_summary_warns_on_recursive_delete() -> None:
    for argv in (
        ["rm", "-rf", "tmp/build-cache"],
        ["rm", "-r", "tmp/build-cache"],
        ["rm", "-fr", "tmp/build-cache"],
    ):
        summary = approval_display_summary(
            call("execute.v1", {"argv": argv}, ToolRisk.COMMAND)
        )
        encoded = json.dumps(summary)
        assert summary == {
            "executable": "rm",
            "argument_count": 2,
            "warnings": ["destructive_recursive_delete"],
        }
        assert "tmp/build-cache" not in encoded
        assert all(warning.isidentifier() for warning in summary["warnings"])


def test_command_summary_warns_on_git_reset_hard() -> None:
    summary = approval_display_summary(
        call(
            "execute.v1",
            {"argv": ["git", "reset", "--hard", "origin/topic-branch"]},
            ToolRisk.COMMAND,
        )
    )

    encoded = json.dumps(summary)
    assert summary == {
        "executable": "git",
        "argument_count": 3,
        "warnings": ["destructive_git_reset"],
    }
    assert "origin/topic-branch" not in encoded
    assert "--hard" not in encoded


def test_command_summary_warns_on_force_push() -> None:
    for argv in (
        ["git", "push", "--force", "origin", "topic-branch"],
        ["git", "push", "-f", "origin", "topic-branch"],
    ):
        summary = approval_display_summary(
            call("execute.v1", {"argv": argv}, ToolRisk.COMMAND)
        )
        encoded = json.dumps(summary)
        assert summary == {
            "executable": "git",
            "argument_count": 4,
            "warnings": ["destructive_force_push"],
        }
        assert "topic-branch" not in encoded
        assert "origin" not in encoded
        assert "--force" not in encoded
        assert "-f" not in encoded


def test_approval_status_has_only_durable_contract_values() -> None:
    assert {status.value for status in ApprovalStatus} == {
        "pending",
        "approved",
        "denied",
        "expired",
        "invalidated",
    }
