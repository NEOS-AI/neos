from __future__ import annotations

import pytest

from neos.coding.domain.approvals import ApprovalPolicyOutcome, evaluate_approval
from neos.coding.tools.registry import (
    CodingToolRegistry,
    ToolRisk,
    ToolValidationError,
)

pytestmark = pytest.mark.no_db


def registry() -> CodingToolRegistry:
    return CodingToolRegistry.default(
        command_allowlist=frozenset(
            {"pytest", "ruff", "mypy", "pnpm", "git"}
        ),
        max_command_timeout_sec=30,
        max_command_output_bytes=4096,
        max_command_stdin_bytes=8,
        allowed_env_names=frozenset({"HOME", "PATH"}),
    )


def test_default_registry_exports_stable_versioned_definitions() -> None:
    definitions = registry().definitions()

    assert [item.name for item in definitions] == [
        "list_tree.v1",
        "stat.v1",
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "edit_file.v1",
        "write_file.v1",
        "mkdir.v1",
        "rm.v1",
        "mv.v1",
        "chmod.v1",
        "todo_write.v1",
        "execute.v1",
        "set_phase.v1",
        "ask_user.v1",
        "load_skill.v1",
        "search_tools.v1",
    ]
    assert all(item.input_schema["additionalProperties"] is False for item in definitions)
    names = [item.name for item in definitions]
    assert names.index("edit_file.v1") == names.index("write_file.v1") - 1
    assert names.index("todo_write.v1") == names.index("execute.v1") - 1
    assert "git_status.v1" not in names
    assert "web_fetch.v1" not in names
    assert "spawn_agent.v1" not in names
    revealed = [
        item.name
        for item in registry().definitions(
            revealed=frozenset({"git_status.v1", "web_fetch.v1", "spawn_agent.v1"})
        )
    ]
    assert "git_status.v1" in revealed
    assert "web_fetch.v1" in revealed
    assert "spawn_agent.v1" in revealed


def test_explore_definitions_omit_write_and_execute() -> None:
    names = [item.name for item in registry().definitions(phase="explore")]

    assert "edit_file.v1" not in names
    assert "write_file.v1" not in names
    assert "mkdir.v1" not in names
    assert "rm.v1" not in names
    assert "mv.v1" not in names
    assert "chmod.v1" not in names
    assert "execute.v1" not in names
    assert "read_file.v1" in names
    assert "glob_files.v1" in names
    assert "search_tools.v1" in names
    assert "set_phase.v1" in names
    assert "ask_user.v1" in names
    assert "load_skill.v1" in names
    assert "spawn_agent.v1" not in names
    hidden = registry().validate(
        "write_file.v1", {"path": "src/main.py", "content": "pass\n"}
    )
    assert hidden.name == "write_file.v1"


def test_load_skill_accepts_catalog_names() -> None:
    pdf = registry().validate("load_skill.v1", {"name": "pdf"})
    verify = registry().validate("load_skill.v1", {"name": "verify"})

    assert pdf.input["name"] == "pdf"
    assert verify.input["name"] == "verify"
    assert registry().decide("load_skill.v1", {"name": "commit"}).allowed is True


def test_ask_user_requires_approval() -> None:
    call = registry().validate(
        "ask_user.v1", {"questions": ["Which test runner should I keep?"]}
    )

    assert call.risk is ToolRisk.USER_QUESTION
    assert evaluate_approval(call) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_search_text_accepts_before_and_after_context() -> None:
    call = registry().validate(
        "search_text.v1",
        {"query": "needle", "before": 2, "after": 3},
    )
    denied = registry().decide(
        "search_text.v1", {"query": "needle", "before": 21}
    )

    assert call.risk is ToolRisk.READ_ONLY
    assert call.input["before"] == 2
    assert call.input["after"] == 3
    assert call.input["output_mode"] == "content"
    assert call.input["ignore_case"] is False
    assert call.input["multiline"] is False
    assert call.input["context"] == 0
    assert call.input["path"] is None
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


def test_search_text_accepts_grep_schema_extras() -> None:
    call = registry().validate(
        "search_text.v1",
        {
            "query": "needle",
            "ignore_case": True,
            "multiline": True,
            "context": 4,
            "path": "src/./lib",
            "limit": 250,
        },
    )
    denied = registry().decide(
        "search_text.v1", {"query": "needle", "limit": 251}
    )
    escaped = registry().decide(
        "search_text.v1", {"query": "needle", "path": "../secret"}
    )

    assert call.input["ignore_case"] is True
    assert call.input["multiline"] is True
    assert call.input["context"] == 4
    assert call.input["path"] == "src/lib"
    assert call.input["limit"] == 250
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"
    assert escaped.allowed is False
    assert escaped.reason_code.startswith("policy_workspace_path_")


def test_search_text_accepts_output_mode() -> None:
    tools = registry()
    defaulted = tools.validate("search_text.v1", {"query": "needle"})
    files = tools.validate(
        "search_text.v1", {"query": "needle", "output_mode": "files"}
    )
    count = tools.validate(
        "search_text.v1", {"query": "needle", "output_mode": "count"}
    )
    content = tools.validate(
        "search_text.v1", {"query": "needle", "output_mode": "content"}
    )
    denied = tools.decide(
        "search_text.v1", {"query": "needle", "output_mode": "raw"}
    )

    assert defaulted.input["output_mode"] == "content"
    assert files.input["output_mode"] == "files"
    assert count.input["output_mode"] == "count"
    assert content.input["output_mode"] == "content"
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


def test_glob_files_is_read_only_and_rejects_escape() -> None:
    allowed = registry().validate(
        "glob_files.v1", {"pattern": "src/**/*.py", "limit": 20}
    )
    denied = registry().decide("glob_files.v1", {"pattern": "../secret"})

    assert allowed.risk is ToolRisk.READ_ONLY
    assert allowed.input == {
        "pattern": "src/**/*.py",
        "limit": 20,
        "path": None,
    }
    assert denied.allowed is False
    assert denied.reason_code.startswith("policy_workspace_path_")


def test_spawn_agent_and_web_fetch_are_read_only() -> None:
    spawn = registry().validate(
        "spawn_agent.v1", {"prompt": "inspect src", "max_turns": 2}
    )
    fetch = registry().validate(
        "web_fetch.v1", {"url": "https://example.com/doc"}
    )

    assert spawn.risk is ToolRisk.READ_ONLY
    assert spawn.input == {"prompt": "inspect src", "max_turns": 2}
    assert fetch.risk is ToolRisk.READ_ONLY
    assert fetch.input == {"url": "https://example.com/doc"}


def test_implement_spawn_is_workspace_write() -> None:
    spawn = registry().validate(
        "spawn_agent.v1",
        {"prompt": "add a helper", "max_turns": 2, "spec": "implement"},
    )
    assert spawn.risk is ToolRisk.WORKSPACE_WRITE
    assert spawn.input["spec"] == "implement"


def test_definitions_defer_non_core_until_revealed(monkeypatch) -> None:
    monkeypatch.setattr(
        "neos.coding.tools.registry._deferred_tools_threshold",
        lambda: 1,
    )
    tools = registry()
    names = [item.name for item in tools.definitions()]

    assert "search_tools.v1" in names
    assert "read_file.v1" in names
    assert "glob_files.v1" in names
    assert "spawn_agent.v1" not in names
    assert "web_fetch.v1" not in names
    assert "git_status.v1" not in names

    revealed = [
        item.name
        for item in tools.definitions(revealed=frozenset({"spawn_agent.v1"}))
    ]
    assert "spawn_agent.v1" in revealed
    assert "web_fetch.v1" not in revealed


def test_search_definitions_select_and_required_terms() -> None:
    selected = CodingToolRegistry.search_definitions(
        "select:web_fetch.v1,write_file.v1,git_status.v1"
    )
    names = [item["name"] for item in selected]
    assert "web_fetch.v1" in names
    assert "git_status.v1" in names
    assert "write_file.v1" not in names
    assert "read_file.v1" not in names

    required = CodingToolRegistry.search_definitions("+fetch")
    required_names = [item["name"] for item in required]
    assert "web_fetch.v1" in required_names
    assert "git_status.v1" not in required_names
    assert all(
        "fetch" in item["name"].casefold()
        or "fetch" in str(item["description"]).casefold()
        for item in required
    )


def test_search_definitions_honors_phase_hide_and_skips_core() -> None:
    explore = CodingToolRegistry.search_definitions("spawn", phase="explore")
    implement = CodingToolRegistry.search_definitions("spawn", phase="implement")
    writes = CodingToolRegistry.search_definitions(
        "select:write_file.v1,spawn_agent.v1", phase="explore"
    )
    write_names = [item["name"] for item in writes]

    assert all(item["name"] != "spawn_agent.v1" for item in explore)
    assert any(item["name"] == "spawn_agent.v1" for item in implement)
    assert "write_file.v1" not in write_names
    assert "spawn_agent.v1" not in write_names


def test_control_plane_tools_hidden_when_subagent_disabled() -> None:
    names = CodingToolRegistry.deferred_tool_names(subagent_enabled=False)
    assert "subagent_list.v1" not in names
    assert "subagent_steer.v1" not in names
    assert "spawn_agent.v1" in names
    hidden = CodingToolRegistry.search_definitions(
        "select:subagent_list.v1,subagent_steer.v1,spawn_agent.v1",
        subagent_enabled=False,
    )
    found = {item["name"] for item in hidden}
    assert found == {"spawn_agent.v1"}
    shown = CodingToolRegistry.search_definitions(
        "select:subagent_list.v1,subagent_steer.v1",
        subagent_enabled=True,
    )
    assert {item["name"] for item in shown} == {
        "subagent_list.v1",
        "subagent_steer.v1",
    }


def test_load_skill_input_accepts_optional_reference() -> None:
    with_ref = registry().validate(
        "load_skill.v1", {"name": "verify", "reference": "hooks.md"}
    )
    with_path = registry().validate(
        "load_skill.v1", {"name": "verify", "path": "hooks.md"}
    )
    bare = registry().validate("load_skill.v1", {"name": "verify"})

    assert with_ref.input["name"] == "verify"
    assert with_ref.input["reference"] == "hooks.md"
    assert with_path.input["path"] == "hooks.md"
    assert bare.input.get("reference") is None


def test_read_file_is_read_only_and_normalizes_path() -> None:
    call = registry().validate("read_file.v1", {"path": "src/./main.py"})

    assert call.risk is ToolRisk.READ_ONLY
    assert call.input == {"path": "src/main.py", "offset": 1, "limit": None}


def test_read_file_accepts_optional_offset_and_limit() -> None:
    sliced = registry().validate(
        "read_file.v1", {"path": "src/main.py", "offset": 3, "limit": 20}
    )
    extra = registry().decide(
        "read_file.v1", {"path": "src/main.py", "surprise": True}
    )

    assert sliced.input == {"path": "src/main.py", "offset": 3, "limit": 20}
    assert extra.allowed is False
    assert extra.reason_code == "policy_schema_invalid"


def test_todo_write_is_read_only_and_accepts_optional_id() -> None:
    call = registry().validate(
        "todo_write.v1",
        {
            "todos": [
                {
                    "id": "t1",
                    "content": "Read the file",
                    "status": "in_progress",
                },
                {"content": "Edit the file", "status": "pending"},
                {"content": "Run tests", "status": "completed"},
            ]
        },
    )

    assert call.risk is ToolRisk.READ_ONLY
    assert call.input["todos"] == [
        {"id": "t1", "content": "Read the file", "status": "in_progress"},
        {"id": None, "content": "Edit the file", "status": "pending"},
        {"id": None, "content": "Run tests", "status": "completed"},
    ]


def test_write_file_is_workspace_write_and_denies_git_control_files() -> None:
    allowed = registry().validate(
        "write_file.v1", {"path": "src/main.py", "content": "pass\n"}
    )
    denied = registry().decide(
        "write_file.v1",
        {"path": ".git/hooks/pre-commit", "content": "exit 0"},
    )
    bare = registry().decide(
        "write_file.v1",
        {"path": "HEAD", "content": "ref: refs/heads/main"},
    )

    assert allowed.risk is ToolRisk.WORKSPACE_WRITE
    assert allowed.input["parents"] is False
    assert denied.allowed is False
    assert denied.reason_code == "policy_protected_git_path"
    assert bare.allowed is False
    assert bare.reason_code in {
        "policy_workspace_bare_git_path",
        "policy_protected_git_path",
    }


def test_write_file_parents_defaults_to_false_and_is_opt_in() -> None:
    defaulted = registry().validate(
        "write_file.v1", {"path": "src/main.py", "content": "pass\n"}
    )
    enabled = registry().validate(
        "write_file.v1",
        {"path": "nested/a.txt", "content": "x", "parents": True},
    )
    denied = registry().decide(
        "write_file.v1",
        {"path": "src/main.py", "content": "pass\n", "parents": "sometimes"},
    )

    assert defaulted.input["parents"] is False
    assert enabled.input["parents"] is True
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


def test_edit_file_is_workspace_write_and_denies_git_control_files() -> None:
    allowed = registry().validate(
        "edit_file.v1",
        {
            "path": "src/./main.py",
            "old_string": "pass",
            "new_string": "return 1",
        },
    )
    denied = registry().decide(
        "edit_file.v1",
        {
            "path": ".git/hooks/pre-commit",
            "old_string": "exit 0",
            "new_string": "exit 1",
        },
    )

    assert allowed.risk is ToolRisk.WORKSPACE_WRITE
    assert allowed.input == {
        "path": "src/main.py",
        "old_string": "pass",
        "new_string": "return 1",
        "replace_all": False,
    }
    assert denied.allowed is False
    assert denied.reason_code == "policy_protected_git_path"


def test_tool_descriptions_state_when_not_to_use_execute_or_write() -> None:
    descriptions = {item.name: item.description for item in registry().definitions()}
    search = descriptions["search_text.v1"]
    execute = descriptions["execute.v1"]
    edit = descriptions["edit_file.v1"]

    assert "execute.v1" in search
    assert "rg" in search or "grep" in search
    assert "-c" in execute
    assert "network" in execute or "git" in execute
    assert "old_string" in edit
    assert "unique" in edit
    assert "read first" in edit.lower()
    todo = descriptions["todo_write.v1"]
    assert "3+" in todo
    assert "one-line" in todo


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret", "bad\0name"])
def test_paths_outside_workspace_are_denied(path: str) -> None:
    decision = registry().decide("read_file.v1", {"path": path})

    assert decision.allowed is False
    assert decision.reason_code.startswith("policy_workspace_path_")


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["bash", "-c", "pytest"], "policy_shell_command_denied"),
        (["git", "push"], "policy_git_operation_denied"),
        (["git", "reset", "--hard"], "policy_git_operation_denied"),
        (["git", "clean", "-fd"], "policy_git_operation_denied"),
        (["curl", "https://example.com"], "policy_network_client_denied"),
        (["pnpm", "publish"], "policy_publish_denied"),
    ],
)
def test_command_policy_denies_unsafe_argv(
    argv: list[str], reason: str
) -> None:
    decision = registry().decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    "argv",
    [
        ["cat", "README.md"],
        ["rg", "needle"],
        ["find", "."],
        ["grep", "x"],
        ["sed", "s/a/b/"],
        ["awk", "{print}"],
        ["env", "cat", "README.md"],
        ["busybox", "grep", "x"],
        ["xargs", "rg", "needle"],
        ["env", "sed", "s/a/b/"],
        ["busybox", "awk", "{print}"],
    ],
)
def test_dedicated_tools_are_hard_denied_even_when_allowlisted(
    argv: list[str],
) -> None:
    unsafe = CodingToolRegistry.default(
        command_allowlist=frozenset({argv[0], argv[-2] if len(argv) > 2 else argv[0], "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dedicated_tool_required"


@pytest.mark.parametrize(
    ("argv", "tool", "denied"),
    [
        (["cat", "README.md"], "read_file.v1", "cat"),
        (["rg", "needle"], "search_text.v1", "rg"),
        (["find", "."], "glob_files.v1", "find"),
        (["sed", "s/a/b/"], "edit_file.v1", "sed"),
        (["env", "cat", "README.md"], "read_file.v1", "cat"),
    ],
)
def test_dedicated_tool_denial_includes_fix_note(
    argv: list[str], tool: str, denied: str
) -> None:
    unsafe = CodingToolRegistry.default(
        command_allowlist=frozenset({argv[0], "cat", "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dedicated_tool_required"
    assert decision.fix_note is not None
    assert tool in decision.fix_note
    assert denied in decision.fix_note
    assert "README.md" not in decision.fix_note


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-c", "print(1)"],
        ["python3", "-c", "print(1)"],
        ["node", "-e", "console.log(1)"],
        ["nodejs", "-e", "console.log(1)"],
        ["perl", "-e", "print 1"],
        ["ruby", "-e", "puts 1"],
        ["php", "-r", "echo 1;"],
        ["lua", "-e", "print(1)"],
        ["env", "python3", "-c", "print(1)"],
    ],
)
def test_inline_interpreter_argv_is_denied(argv: list[str]) -> None:
    unsafe = CodingToolRegistry.default(
        command_allowlist=frozenset({argv[0], "python3", "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_inline_interpreter_denied"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "/tmp/test.py"],
        ["ruff", "check", "../secret"],
        ["mypy", "src/../../etc/passwd"],
    ],
)
def test_execute_path_operands_outside_workspace_are_denied(
    argv: list[str],
) -> None:
    decision = registry().decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_command_path_denied"


def test_execute_secret_path_operands_are_denied() -> None:
    decision = registry().decide("execute.v1", {"argv": ["pytest", ".env"]})
    cased = registry().decide("execute.v1", {"argv": ["ruff", "check", "svc/.ENV"]})
    flagged = registry().decide(
        "execute.v1", {"argv": ["ruff", "--config=/etc/passwd"]}
    )
    flagged_secret = registry().decide(
        "execute.v1", {"argv": ["ruff", "--config=../.env"]}
    )

    assert decision.allowed is False
    assert decision.reason_code == "policy_secret_path_denied"
    assert cased.allowed is False
    assert cased.reason_code == "policy_secret_path_denied"
    assert flagged.allowed is False
    assert flagged.reason_code == "policy_command_path_denied"
    assert flagged_secret.allowed is False
    assert flagged_secret.reason_code == "policy_secret_path_denied"


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["env", "sh", "-c", "pytest"], "policy_shell_command_denied"),
        (["env", "bash", "-c", "echo hi"], "policy_shell_command_denied"),
        (["busybox", "sh", "-c", "id"], "policy_shell_command_denied"),
        (["env", "curl", "https://example.com"], "policy_network_client_denied"),
        (["env", "git", "push"], "policy_git_operation_denied"),
        (["env", "pnpm", "install"], "policy_network_operation_denied"),
    ],
)
def test_wrapper_does_not_bypass_shell_network_or_git_denies(
    argv: list[str], reason: str
) -> None:
    unsafe = CodingToolRegistry.default(
        command_allowlist=frozenset({"env", "busybox", "sh", "bash", "curl", "git", "pnpm"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    "argv",
    [
        ["rm", "/"],
        ["rm", "/*"],
        ["rm", "*"],
        ["rm", "~"],
        ["rm", "-rf", "/"],
        ["rmdir", "/tmp"],
        ["rm", "../outside"],
        ["env", "rm", "-rf", "/"],
    ],
)
def test_dangerous_removal_argv_is_denied(argv: list[str]) -> None:
    unsafe = CodingToolRegistry.default(
        command_allowlist=frozenset({"rm", "rmdir", "env", "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dangerous_removal"


def test_ask_user_accepts_mcq_questions() -> None:
    call = registry().validate(
        "ask_user.v1",
        {
            "questions": [
                {
                    "prompt": "Which runner?",
                    "options": [
                        {"label": "pytest", "description": "default"},
                        {"label": "nox"},
                    ],
                }
            ]
        },
    )

    assert call.input["questions"][0]["prompt"] == "Which runner?"
    assert len(call.input["questions"][0]["options"]) == 2


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["bash", "-c", "pytest"], "policy_shell_command_denied"),
        (["curl", "https://example.com"], "policy_network_client_denied"),
        (["wget", "https://example.com"], "policy_network_client_denied"),
        (["pnpm", "install"], "policy_network_operation_denied"),
        (["pnpm", "add", "left-pad"], "policy_network_operation_denied"),
    ],
)
def test_absolute_denials_override_misconfigured_allowlist(
    argv: list[str], reason: str
) -> None:
    unsafe_registry = CodingToolRegistry.default(
        command_allowlist=frozenset({"bash", "curl", "wget", "pnpm"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe_registry.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == reason


def test_executable_must_be_a_bare_allowlisted_name() -> None:
    decision = registry().decide(
        "execute.v1", {"argv": ["/tmp/pytest", "-q"]}
    )

    assert decision.allowed is False
    assert decision.reason_code == "policy_executable_path_denied"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "-q"],
        ["ruff", "check", "."],
        ["mypy", "src"],
        ["pnpm", "test"],
        ["git", "status", "--short"],
        ["git", "diff", "--cached"],
        ["git", "log", "-5"],
    ],
)
def test_allowlisted_development_commands_are_accepted(
    argv: list[str],
) -> None:
    call = registry().validate("execute.v1", {"argv": argv})

    assert call.risk is ToolRisk.COMMAND
    assert call.input["argv"] == argv


@pytest.mark.parametrize("argv", [["git"], ["git", "commit"], ["git", "checkout"]])
def test_git_execute_only_allows_read_only_subcommands(argv: list[str]) -> None:
    decision = registry().decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_git_operation_denied"


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "-c", "core.fsmonitor=/tmp/evil", "status"],
        ["git", "-c=core.fsmonitor=/tmp/evil", "status"],
        ["git", "--config-env", "core.fsmonitor=HOOK", "status"],
        ["git", "--config-env=core.fsmonitor=HOOK", "diff"],
        ["git", "--exec-path", "/tmp", "log"],
        ["git", "--exec-path=/tmp/git-core", "status"],
        ["env", "git", "--exec-path=/tmp", "status"],
        ["git", "status", "--config-env=core.fsmonitor=HOOK"],
        ["git", "-calias.status=!touch pwned", "status"],
        ["git", "-ccore.fsmonitor=/tmp/evil", "diff"],
    ],
)
def test_git_dangerous_flags_are_denied(argv: list[str]) -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"git", "env", "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = tools.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_git_operation_denied"


@pytest.mark.parametrize(
    "argv",
    [
        ["pnpm", "exec", "cat", "README.md"],
        ["npm", "exec", "cat", "README.md"],
        ["yarn", "dlx", "cat", "README.md"],
        ["npx", "exec", "grep", "x"],
        ["pnpm", "exec", "--", "rg", "needle"],
        ["env", "pnpm", "exec", "sed", "s/a/b/"],
        ["pnpm", "exec", "env", "cat", "README.md"],
        ["pnpm", "exec", "timeout", "5", "cat", "README.md"],
    ],
)
def test_package_exec_unwraps_dedicated_command(argv: list[str]) -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"pnpm", "npm", "yarn", "npx", "env", "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = tools.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dedicated_tool_required"


def test_package_exec_unwraps_inline_interpreter() -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"pnpm", "pytest"}),
        allowed_env_names=frozenset(),
    )

    nested = CodingToolRegistry.default(
        command_allowlist=frozenset({"pnpm", "env", "pytest"}),
        allowed_env_names=frozenset(),
    )
    decision = tools.decide(
        "execute.v1", {"argv": ["pnpm", "exec", "python", "-cprint(1)"]}
    )
    wrapped = nested.decide(
        "execute.v1",
        {"argv": ["pnpm", "exec", "env", "python", "-c", "print(1)"]},
    )

    assert decision.allowed is False
    assert decision.reason_code == "policy_inline_interpreter_denied"
    assert wrapped.allowed is False
    assert wrapped.reason_code == "policy_inline_interpreter_denied"


@pytest.mark.parametrize(
    "argv",
    [
        ["timeout", "5", "cat", "README.md"],
        ["nice", "cat", "README.md"],
        ["nohup", "cat", "README.md"],
        ["time", "cat", "README.md"],
        ["stdbuf", "-o0", "cat", "README.md"],
        ["command", "cat", "README.md"],
        ["timeout", "--", "cat", "README.md"],
        ["env", "timeout", "5", "cat", "README.md"],
    ],
)
def test_additional_wrappers_unwrap_dedicated_commands(argv: list[str]) -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset(
            {"timeout", "nice", "nohup", "time", "stdbuf", "command", "env", "pytest"}
        ),
        allowed_env_names=frozenset(),
    )

    decision = tools.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dedicated_tool_required"


def test_timeout_wrapping_allowlisted_command_stays_allowed() -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"timeout", "pytest"}),
        allowed_env_names=frozenset(),
    )

    call = tools.validate("execute.v1", {"argv": ["timeout", "5", "pytest", "-q"]})

    assert call.input["argv"] == ["timeout", "5", "pytest", "-q"]


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["rm", "--", "/"], "policy_dangerous_removal"),
        (["rm", "--", "-/../outside"], "policy_dangerous_removal"),
        (["pytest", "--", "/tmp/test.py"], "policy_command_path_denied"),
        (["ruff", "--", "../.env"], "policy_secret_path_denied"),
    ],
)
def test_double_dash_ends_flags_for_path_and_removal_checks(
    argv: list[str], reason: str
) -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"rm", "pytest", "ruff"}),
        allowed_env_names=frozenset(),
    )

    decision = tools.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-cprint(1)"],
        ["python3", "-c=print(1)"],
        ["node", "--eval", "console.log(1)"],
        ["nodejs", "--eval=console.log(1)"],
        ["perl", "-eprint 1"],
        ["ruby", "-p"],
        ["lua", "-eprint(1)"],
        ["env", "python3", "-cprint(1)"],
    ],
)
def test_attached_interpreter_flags_are_denied(argv: list[str]) -> None:
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset({argv[0], "python3", "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = tools.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_inline_interpreter_denied"


def test_execute_caps_cannot_exceed_server_limits() -> None:
    timeout = registry().decide(
        "execute.v1", {"argv": ["pytest"], "timeout_sec": 31}
    )
    output = registry().decide(
        "execute.v1", {"argv": ["pytest"], "max_output_bytes": 4097}
    )

    assert timeout.reason_code == "policy_command_timeout_exceeded"
    assert output.reason_code == "policy_command_output_exceeded"


def test_execute_stdin_uses_utf8_byte_limit() -> None:
    accepted = registry().validate(
        "execute.v1", {"argv": ["pytest"], "stdin": "가나"}
    )
    denied = registry().decide(
        "execute.v1", {"argv": ["pytest"], "stdin": "가나다"}
    )

    assert accepted.input["stdin"] == "가나"
    assert denied.reason_code == "policy_command_stdin_exceeded"


def test_execute_environment_names_are_allowlisted() -> None:
    accepted = registry().validate(
        "execute.v1",
        {"argv": ["pytest"], "env": {"HOME": "/workspace"}},
    )
    denied = registry().decide(
        "execute.v1",
        {"argv": ["pytest"], "env": {"TOKEN": "secret"}},
    )

    assert accepted.input["env"] == {"HOME": "/workspace"}
    assert denied.reason_code == "policy_environment_name_denied"


@pytest.mark.parametrize(
    ("name", "input"),
    [
        ("unknown.v1", {}),
        ("read_file.v1", {"path": "a", "surprise": True}),
        ("read_file.v1", {"path": "a", "offset": 0}),
        ("read_file.v1", {"path": "a", "limit": 0}),
        ("read_file.v1", {"path": "a", "limit": 5001}),
        ("search_text.v1", {"query": "x", "limit": 0}),
        ("search_text.v1", {"query": "x", "before": 21}),
        ("search_text.v1", {"query": "x", "after": -1}),
        ("search_text.v1", {"query": "x", "output_mode": "raw"}),
        ("search_text.v1", {"query": "x", "output_mode": "grep"}),
        ("glob_files.v1", {"pattern": ""}),
        ("glob_files.v1", {"pattern": "*.py", "limit": 0}),
        ("glob_files.v1", {"pattern": "*.py", "limit": 501}),
        ("web_fetch.v1", {}),
        ("search_tools.v1", {"query": ""}),
        ("spawn_agent.v1", {"prompt": "x", "max_turns": 0}),
        ("spawn_agent.v1", {"prompt": "x", "max_turns": 9}),
        ("subagent_steer.v1", {"run_id": "sa_1", "text": "x" * 2001}),
        ("git_log.v1", {"limit": 101}),
        (
            "edit_file.v1",
            {"path": "a", "old_string": "x", "new_string": "y", "surprise": True},
        ),
        ("todo_write.v1", {"todos": []}),
        ("todo_write.v1", {"todos": [{"content": "", "status": "pending"}]}),
        ("todo_write.v1", {"todos": [{"content": "x", "status": "blocked"}]}),
        ("todo_write.v1", {"todos": [{"content": "x", "status": "pending", "surprise": True}]}),
        ("execute.v1", {"argv": []}),
        ("set_phase.v1", {"phase": "ship"}),
        ("ask_user.v1", {"questions": []}),
        ("ask_user.v1", {"questions": ["a", "b", "c", "d", "e"]}),
        ("load_skill.v1", {"name": ""}),
    ],
)
def test_unknown_or_invalid_calls_fail_closed(
    name: str, input: dict[str, object]
) -> None:
    decision = registry().decide(name, input)

    assert decision.allowed is False
    assert decision.reason_code in {
        "policy_unknown_tool",
        "policy_schema_invalid",
    }
    with pytest.raises(ToolValidationError):
        registry().validate(name, input)
