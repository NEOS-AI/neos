from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Protocol


_EXECUTABLE_CATEGORIES = {
    "bash": "shell",
    "git": "git",
    "node": "node",
    "npm": "node",
    "pnpm": "node",
    "python": "python",
    "python3": "python",
    "rg": "search",
    "sh": "shell",
}
_CODING_PROVIDERS = {"memory", "docker", "managed", "kubernetes"}
_CODING_TOOLS = {
    "list_tree.v1",
    "stat.v1",
    "read_file.v1",
    "search_text.v1",
    "git_status.v1",
    "git_diff.v1",
    "git_log.v1",
    "write_file.v1",
    "execute.v1",
}
_CODING_OPERATIONS = {"validate", "claim", "execute", "checkpoint"}
_CODING_OUTCOMES = {"allowed", "denied", "ok", "error", "reused"}
_CODING_ERROR_CODES = {
    "policy_unknown_tool",
    "policy_schema_invalid",
    "policy_executable_not_allowed",
    "policy_executable_path_denied",
    "policy_shell_command_denied",
    "policy_network_client_denied",
    "policy_network_operation_denied",
    "policy_publish_denied",
    "policy_git_operation_denied",
    "policy_command_timeout_exceeded",
    "policy_command_output_exceeded",
    "policy_command_stdin_exceeded",
    "policy_environment_name_denied",
    "policy_protected_git_path",
    "sandbox_timeout",
    "sandbox_policy_violation",
    "sandbox_not_found",
    "sandbox_error",
    "command_failed",
    "tool_execution_failed",
    "tool_outcome_unknown",
}
_logger = logging.getLogger(__name__)


def bounded_executable_category(executable: str) -> str:
    name = executable.rsplit("/", 1)[-1]
    return _EXECUTABLE_CATEGORIES.get(name, "other")


def _bounded_error_code(error_code: str | None) -> str | None:
    if error_code is None or error_code in _CODING_ERROR_CODES:
        return error_code
    return "other"


@dataclass(frozen=True, slots=True)
class SandboxAuditEvent:
    sandbox_id: str
    operation: str
    executable_category: str
    environment_names: tuple[str, ...]
    stdin_bytes: int
    stdout_bytes: int
    outcome: str
    error_code: str | None = None

    @classmethod
    def for_command(
        cls,
        *,
        sandbox_id: str,
        argv: tuple[str, ...],
        env: Mapping[str, str],
        stdin_bytes: int,
        stdout_bytes: int,
        outcome: str,
        error_code: str | None = None,
    ) -> SandboxAuditEvent:
        return cls(
            sandbox_id=sandbox_id,
            operation="command",
            executable_category=bounded_executable_category(argv[0] if argv else ""),
            environment_names=tuple(sorted(env)),
            stdin_bytes=max(0, stdin_bytes),
            stdout_bytes=max(0, stdout_bytes),
            outcome=outcome,
            error_code=_bounded_error_code(error_code),
        )


@dataclass(frozen=True, slots=True)
class CodingToolAuditEvent:
    """Content-free metadata for a registered coding tool execution."""

    provider: str
    tool: str
    operation: str
    outcome: str
    error_code: str | None = None

    @classmethod
    def from_result(
        cls,
        *,
        provider: str,
        tool: str,
        operation: str,
        outcome: str,
        error_code: str | None = None,
    ) -> CodingToolAuditEvent:
        bounded_outcome = outcome if outcome in _CODING_OUTCOMES else "error"
        return cls(
            provider=provider if provider in _CODING_PROVIDERS else "other",
            tool=tool if tool in _CODING_TOOLS else "unknown",
            operation=operation if operation in _CODING_OPERATIONS else "other",
            outcome=bounded_outcome,
            error_code=_bounded_error_code(error_code),
        )


@dataclass(frozen=True, slots=True)
class CodingApprovalAuditEvent:
    """Sanitized, bounded metadata for an approval lifecycle transition."""

    tool: str
    risk: str
    outcome: str


class CodingAuditSink(Protocol):
    async def emit(
        self, event: CodingToolAuditEvent | CodingApprovalAuditEvent
    ) -> None: ...


class NullCodingAuditSink:
    async def emit(
        self, event: CodingToolAuditEvent | CodingApprovalAuditEvent
    ) -> None:
        return None


class LoggingCodingAuditSink:
    async def emit(
        self, event: CodingToolAuditEvent | CodingApprovalAuditEvent
    ) -> None:
        _logger.info("coding_tool_audit", extra={"coding_audit": asdict(event)})
