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
