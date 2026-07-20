from __future__ import annotations

import pytest

from neos.coding.tools.registry import (
    CodingToolRegistry,
    ToolRisk,
    ToolValidationError,
)


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
        "git_status.v1",
        "git_diff.v1",
        "git_log.v1",
        "write_file.v1",
        "execute.v1",
    ]
    assert all(item.input_schema["additionalProperties"] is False for item in definitions)


def test_read_file_is_read_only_and_normalizes_path() -> None:
    call = registry().validate("read_file.v1", {"path": "src/./main.py"})

    assert call.risk is ToolRisk.READ_ONLY
    assert call.input == {"path": "src/main.py"}


def test_write_file_is_workspace_write_and_denies_git_control_files() -> None:
    allowed = registry().validate(
        "write_file.v1", {"path": "src/main.py", "content": "pass\n"}
    )
    denied = registry().decide(
        "write_file.v1",
        {"path": ".git/hooks/pre-commit", "content": "exit 0"},
    )

    assert allowed.risk is ToolRisk.WORKSPACE_WRITE
    assert denied.allowed is False
    assert denied.reason_code == "policy_protected_git_path"


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
        ("search_text.v1", {"query": "x", "limit": 0}),
        ("git_log.v1", {"limit": 101}),
        ("execute.v1", {"argv": []}),
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
