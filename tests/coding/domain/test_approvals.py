import json

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    ApprovalStatus,
    approval_display_summary,
    ask_user_answers_complete,
    adaptive_denial_reason,
    canonical_approval_hash,
    denial_envelope,
    evaluate_approval,
    is_denied_secret_path,
    requires_approval_answers,
)
from neos.coding.redact import redact_sensitive
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


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
        "id_ed25519",
        "keys/id_ed25519",
        ".aws/credentials",
        "svc/.aws/credentials",
        ".envrc",
        "svc/.envrc",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".pgpass",
        ".git-credentials",
        "home/.git-credentials",
        ".neos/secrets/token",
        "svc/.neos/secrets/api",
        ".NEOS/Secrets/token",
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
        ".ENV",
        ".Env.local",
        "svc/.ENV",
        ".Git/config",
        "pkg/.GIT/HEAD",
        ".SSH/id_ed25519",
        "home/.Ssh/config",
        "ID_RSA",
        "keys/Id_Rsa",
        "ID_ED25519",
        "keys/Id_Ed25519",
        ".AWS/credentials",
        "svc/.Aws/Credentials",
        ".ENVRC",
        "svc/.Npmrc",
        ".Pypirc",
        ".NETRC",
        ".Pgpass",
        ".GIT-CREDENTIALS",
    ],
)
def test_secret_dotfile_paths_are_denied_casefold(path: str) -> None:
    read = call("read_file.v1", {"path": path}, ToolRisk.READ_ONLY)
    write = call(
        "write_file.v1",
        {"path": path, "content": "secret"},
        ToolRisk.WORKSPACE_WRITE,
    )
    assert is_denied_secret_path(path)
    assert evaluate_approval(read) is ApprovalPolicyOutcome.DENY
    assert evaluate_approval(write) is ApprovalPolicyOutcome.DENY


def test_execute_argv_secret_operands_are_denied() -> None:
    command = call(
        "execute.v1",
        {"argv": ["pytest", ".env"]},
        ToolRisk.COMMAND,
    )
    nested = call(
        "execute.v1",
        {"argv": ["ruff", "check", "svc/.ENV"]},
        ToolRisk.COMMAND,
    )
    gate = ApprovalGate(approved_always=frozenset({"execute.v1"}))

    flagged = call(
        "execute.v1",
        {"argv": ["ruff", "--config=.env"]},
        ToolRisk.COMMAND,
    )
    assert evaluate_approval(command) is ApprovalPolicyOutcome.DENY
    assert evaluate_approval(nested, gate) is ApprovalPolicyOutcome.DENY
    assert evaluate_approval(flagged) is ApprovalPolicyOutcome.DENY


@pytest.mark.parametrize(
    "path",
    [
        ".bashrc",
        ".ZSHRC",
        "home/.profile",
        ".gitconfig",
        ".gitmodules",
        ".mcp.json",
        ".claude.json",
        ".ripgreprc",
        ".vscode/settings.json",
        ".IDEA/workspace.xml",
        "pkg/.Claude/settings.json",
    ],
)
def test_sensitive_config_writes_require_approval_despite_remember(
    path: str,
) -> None:
    write = call(
        "write_file.v1",
        {"path": path, "content": "export X=1"},
        ToolRisk.WORKSPACE_WRITE,
    )
    edit = call(
        "edit_file.v1",
        {"path": path, "old_string": "a", "new_string": "b"},
        ToolRisk.WORKSPACE_WRITE,
    )
    read = call("read_file.v1", {"path": path}, ToolRisk.READ_ONLY)
    gate = ApprovalGate(approved_always=frozenset({"write_file.v1", "edit_file.v1"}))
    allow_gate = ApprovalGate(allow_tools=frozenset({"write_file.v1"}))
    auto_gate = ApprovalGate(
        mode=ApprovalMode.AUTO,
        always_allow=frozenset({"write_file.v1"}),
    )

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(write, allow_gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(write, auto_gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(edit, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(read) is ApprovalPolicyOutcome.ALLOW


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "src/main.py",
        ".gitignore",
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


def test_instruction_file_writes_require_approval_despite_approved_always() -> None:
    write = call(
        "write_file.v1",
        {"path": "AGENTS.md", "content": "ignore previous"},
        ToolRisk.WORKSPACE_WRITE,
    )
    nested = call(
        "write_file.v1",
        {"path": "docs/CLAUDE.md", "content": "x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    soul = call(
        "edit_file.v1",
        {"path": "SOUL.md", "old_string": "a", "new_string": "b"},
        ToolRisk.WORKSPACE_WRITE,
    )
    cursor = call(
        "write_file.v1",
        {"path": ".cursorrules", "content": "x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    lowercase = call(
        "write_file.v1",
        {"path": "agents.md", "content": "x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    local = call(
        "write_file.v1",
        {"path": "docs/claude.local.md", "content": "x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    local_cased = call(
        "edit_file.v1",
        {"path": "CLAUDE.local.md", "old_string": "a", "new_string": "b"},
        ToolRisk.WORKSPACE_WRITE,
    )
    gate = ApprovalGate(approved_always=frozenset({"write_file.v1", "edit_file.v1"}))
    allow_gate = ApprovalGate(allow_tools=frozenset({"write_file.v1"}))
    auto_gate = ApprovalGate(
        mode=ApprovalMode.AUTO,
        always_allow=frozenset({"write_file.v1"}),
    )

    assert evaluate_approval(write, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(write, allow_gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(write, auto_gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(nested, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(soul, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(cursor, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(lowercase, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(local, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(local_cased, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_execute_instruction_file_operands_require_approval_despite_approved_always() -> None:
    agents = call(
        "execute.v1",
        {"argv": ["sed", "-i", "s/a/b/", "AGENTS.md"]},
        ToolRisk.COMMAND,
    )
    nested = call(
        "execute.v1",
        {"argv": ["cat", "pkg/CLAUDE.md"]},
        ToolRisk.COMMAND,
    )
    gate = ApprovalGate(approved_always=frozenset({"execute.v1"}))
    allow_gate = ApprovalGate(allow_tools=frozenset({"execute.v1"}))
    auto_gate = ApprovalGate(
        mode=ApprovalMode.AUTO,
        always_allow=frozenset({"execute.v1"}),
    )

    assert evaluate_approval(agents, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(nested, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(agents, allow_gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(agents, auto_gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_execute_normal_file_operand_is_not_forced_to_ask_by_instruction_rule() -> None:
    command = call(
        "execute.v1",
        {"argv": ["pytest", "src/main.py"]},
        ToolRisk.COMMAND,
    )
    gate = ApprovalGate(approved_always=frozenset({"execute.v1"}))

    assert evaluate_approval(command) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(command, gate) is ApprovalPolicyOutcome.ALLOW


def test_unattended_write_of_normal_file_is_deny() -> None:
    write = call(
        "write_file.v1",
        {"path": "src/main.py", "content": "value"},
        ToolRisk.WORKSPACE_WRITE,
    )

    assert evaluate_approval(write) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert (
        evaluate_approval(write, ApprovalGate(unattended=True))
        is ApprovalPolicyOutcome.DENY
    )


def test_unattended_write_of_instruction_file_is_deny() -> None:
    write = call(
        "write_file.v1",
        {"path": "AGENTS.md", "content": "ignore previous"},
        ToolRisk.WORKSPACE_WRITE,
    )

    assert (
        evaluate_approval(write, ApprovalGate(unattended=True))
        is ApprovalPolicyOutcome.DENY
    )


def test_unattended_execute_of_instruction_file_is_deny() -> None:
    command = call(
        "execute.v1",
        {"argv": ["sed", "-i", "s/a/b/", "AGENTS.md"]},
        ToolRisk.COMMAND,
    )

    assert (
        evaluate_approval(command, ApprovalGate(unattended=True))
        is ApprovalPolicyOutcome.DENY
    )


def test_attended_instruction_file_write_remains_require_approval() -> None:
    write = call(
        "write_file.v1",
        {"path": "AGENTS.md", "content": "ignore previous"},
        ToolRisk.WORKSPACE_WRITE,
    )

    assert evaluate_approval(write) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert (
        evaluate_approval(write, ApprovalGate(unattended=False))
        is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    )


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
    mcq = approval_display_summary(
        call(
            "ask_user.v1",
            {
                "questions": [
                    {
                        "prompt": "Which runner?",
                        "options": [{"label": "pytest"}, {"label": "nox"}],
                    }
                ]
            },
            ToolRisk.USER_QUESTION,
        )
    )
    assert mcq["questions"] == ["Which runner?"]
    assert mcq["options"] == [["pytest", "nox"]]
    assert ask_user_answers_complete(["Which runner?"], ["pytest"])
    assert not ask_user_answers_complete(["Which runner?"], [""])
    assert not ask_user_answers_complete(["a", "b"], ["yes"])
    assert not ask_user_answers_complete(["a", "b"], ["yes", "   "])
    assert ask_user_answers_complete(["a", "b"], ["yes", "no"])


def test_canonical_hash_is_deterministic_and_binding_sensitive() -> None:
    first = canonical_approval_hash(binding())
    reordered = canonical_approval_hash(dict(reversed(tuple(binding().items()))))

    assert first == reordered
    assert first != canonical_approval_hash(binding(workspace_revision="rev-2"))
    assert first != canonical_approval_hash(
        binding(normalized_input={"path": "src/main.py", "content": "other"})
    )
    assert len(first) == 64


def test_write_summary_exposes_path_and_truncated_preview() -> None:
    long_content = "".join(f"line-{index}-payload\n" for index in range(80))
    short = approval_display_summary(
        call(
            "write_file.v1",
            {"path": "src/main.py", "content": "hello"},
            ToolRisk.WORKSPACE_WRITE,
        )
    )
    summary = approval_display_summary(
        call(
            "write_file.v1",
            {"path": "src/main.py", "content": long_content},
            ToolRisk.WORKSPACE_WRITE,
        )
    )

    encoded = json.dumps(summary)
    assert short["path"] == "src/main.py"
    assert short["preview"] == "hello"
    assert short["truncated"] is False
    assert "content" not in short
    assert summary["path"] == "src/main.py"
    assert "preview" in summary
    assert summary["truncated"] is True
    assert "content" not in summary
    assert long_content not in encoded
    assert summary["preview"].count("\n") <= 40
    assert len(summary["preview"]) <= 2000


def test_edit_summary_exposes_path_and_truncated_patch() -> None:
    old = "\n".join(f"old-{index}" for index in range(80))
    new = "\n".join(f"new-{index}" for index in range(80))
    summary = approval_display_summary(
        call(
            "edit_file.v1",
            {"path": "src/main.py", "old_string": old, "new_string": new},
            ToolRisk.WORKSPACE_WRITE,
        )
    )

    encoded = json.dumps(summary)
    assert summary["path"] == "src/main.py"
    assert "patch" in summary
    assert summary["truncated"] is True
    assert "content" not in summary
    assert old not in encoded
    assert new not in encoded
    assert len(summary["patch"]) <= 2000


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


def test_redact_sensitive_masks_secret_keys_and_clips_long_strings() -> None:
    redacted = redact_sensitive(
        {
            "path": "src/main.py",
            "API_TOKEN": "s3cret",
            "nested": {"password": "hunter2", "ok": 1},
            "note": "x" * 401,
        }
    )
    assert redacted["path"] == "src/main.py"
    assert redacted["API_TOKEN"] == "<redacted>"
    assert redacted["nested"]["password"] == "<redacted>"
    assert redacted["nested"]["ok"] == 1
    assert redacted["note"] == ("x" * 400) + "…"


def test_redact_sensitive_caps_depth() -> None:
    nested: object = {"leaf": "ok"}
    for _ in range(7):
        nested = {"child": nested}
    redacted = redact_sensitive(nested)
    cursor = redacted
    for _ in range(6):
        assert isinstance(cursor, dict)
        cursor = cursor["child"]
    assert cursor == "<redacted>"


def test_denial_envelope_uses_hook_or_policy_and_redacts_excerpt() -> None:
    write = call(
        "write_file.v1",
        {"path": "src/main.py", "content": "raw-secret"},
        ToolRisk.WORKSPACE_WRITE,
    )
    hooked = denial_envelope(write, "policy_hook_denied")
    assert hooked["reason_code"] == "policy_hook_denied"
    assert hooked["status"] == "denied"
    assert hooked["denied_by"] == "hook"
    assert hooked["function_id"] == "write_file.v1"
    assert hooked["reason"] == adaptive_denial_reason("policy_hook_denied")
    assert hooked["reason"] != hooked["reason_code"]
    assert hooked["args_excerpt"]["path"] == "src/main.py"
    assert "content" not in hooked["args_excerpt"]
    assert "preview" not in hooked["args_excerpt"]
    assert "raw-secret" not in json.dumps(hooked)

    command = call(
        "execute.v1",
        {
            "argv": ["pytest", "secret_test.py"],
            "env": {"TOKEN": "raw-secret-token"},
        },
        ToolRisk.COMMAND,
    )
    denied = denial_envelope(command, "policy_approval_denied")
    assert denied["denied_by"] == "user"
    assert denied["function_id"] == "execute.v1"
    assert denied["args_excerpt"] == {
        "executable": "pytest",
        "argument_count": 1,
    }
    assert "raw-secret-token" not in json.dumps(denied)
    assert "secret_test.py" not in json.dumps(denied)


def test_denial_envelope_includes_argv_warnings_in_reason() -> None:
    rm = denial_envelope(
        call("execute.v1", {"argv": ["rm", "-r", "tmp"]}, ToolRisk.COMMAND),
        "policy_dangerous_removal",
    )
    reset = denial_envelope(
        call(
            "execute.v1",
            {"argv": ["git", "reset", "--hard", "HEAD"]},
            ToolRisk.COMMAND,
        ),
        "policy_git_operation_denied",
    )

    assert rm["reason_code"] == "policy_dangerous_removal"
    assert rm["warnings"] == ["destructive_recursive_delete"]
    assert "recursive delete" in rm["reason"]
    assert rm["reason"] != rm["reason_code"]
    assert "warnings" not in rm["args_excerpt"]
    assert reset["reason_code"] == "policy_git_operation_denied"
    assert reset["warnings"] == ["destructive_git_reset"]
    assert "reset --hard" in reset["reason"]
    assert "S00" not in json.dumps(rm)
    assert "S00" not in json.dumps(reset)

    long_rm = denial_envelope(
        call("execute.v1", {"argv": ["rm", "--recursive", "tmp"]}, ToolRisk.COMMAND),
        "policy_dangerous_removal",
    )
    operand = denial_envelope(
        call("execute.v1", {"argv": ["rm", "--", "-r"]}, ToolRisk.COMMAND),
        "policy_dangerous_removal",
    )
    dedicated = denial_envelope(
        call("execute.v1", {"argv": ["rg", "needle"]}, ToolRisk.COMMAND),
        "policy_dedicated_tool_required",
    )
    assert long_rm["warnings"] == ["destructive_recursive_delete"]
    assert "warnings" not in operand
    assert dedicated["reason"] != dedicated["reason_code"]
    assert "dedicated tool" in dedicated["reason"]
