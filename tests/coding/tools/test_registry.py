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
        "git_status.v1",
        "git_diff.v1",
        "git_log.v1",
        "web_fetch.v1",
        "edit_file.v1",
        "write_file.v1",
        "todo_write.v1",
        "execute.v1",
        "set_phase.v1",
        "ask_user.v1",
        "load_skill.v1",
        "search_tools.v1",
        "spawn_agent.v1",
    ]
    assert all(item.input_schema["additionalProperties"] is False for item in definitions)
    names = [item.name for item in definitions]
    assert names.index("edit_file.v1") == names.index("write_file.v1") - 1
    assert names.index("todo_write.v1") == names.index("execute.v1") - 1


def test_explore_definitions_omit_write_and_execute() -> None:
    names = [item.name for item in registry().definitions(phase="explore")]

    assert "edit_file.v1" not in names
    assert "write_file.v1" not in names
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
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


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
    assert allowed.input == {"pattern": "src/**/*.py", "limit": 20}
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

    assert allowed.risk is ToolRisk.WORKSPACE_WRITE
    assert allowed.input["parents"] is False
    assert denied.allowed is False
    assert denied.reason_code == "policy_protected_git_path"


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
    [["cat", "README.md"], ["rg", "needle"], ["find", "."], ["grep", "x"]],
)
def test_dedicated_tools_are_hard_denied_even_when_allowlisted(
    argv: list[str],
) -> None:
    unsafe = CodingToolRegistry.default(
        command_allowlist=frozenset({argv[0], "pytest"}),
        allowed_env_names=frozenset(),
    )

    decision = unsafe.decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dedicated_tool_required"


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
