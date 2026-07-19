from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


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
        executable = argv[0].rsplit("/", 1)[-1] if argv else ""
        return cls(
            sandbox_id=sandbox_id,
            operation="command",
            executable_category=_EXECUTABLE_CATEGORIES.get(
                executable,
                "other",
            ),
            environment_names=tuple(sorted(env)),
            stdin_bytes=max(0, stdin_bytes),
            stdout_bytes=max(0, stdout_bytes),
            outcome=outcome,
            error_code=error_code,
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
        bounded_outcome = outcome if outcome in {"ok", "error", "denied"} else "error"
        return cls(
            provider=provider if provider in _CODING_PROVIDERS else "other",
            tool=tool if tool in _CODING_TOOLS else "unknown",
            operation=operation if operation in _CODING_OPERATIONS else "other",
            outcome=bounded_outcome,
            error_code=error_code,
        )
