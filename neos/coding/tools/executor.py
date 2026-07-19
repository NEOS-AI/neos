from __future__ import annotations

import hashlib
import inspect
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    SandboxError,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxSession,
    SandboxTimeout,
    SearchMatch,
)
from neos.coding.tools.registry import ValidatedToolCall


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Literal["ok", "error", "denied"]
    reason_code: str
    preview: str | None
    original_bytes: int | None
    truncated: bool
    checksum: str | None
    workspace_revision: str
    entries: tuple[Mapping[str, object], ...] = ()
    stdout: Mapping[str, object] | None = None
    stderr: Mapping[str, object] | None = None
    exit_code: int | None = None
    audit: Mapping[str, object] | None = None

    @classmethod
    def ok(cls, *, workspace_revision: str) -> ToolResult:
        return cls("ok", "ok", None, None, False, None, workspace_revision)

    def to_mapping(self) -> Mapping[str, object]:
        return asdict(self)


class SandboxToolExecutor:
    def __init__(self, max_preview_bytes: int, max_entries: int) -> None:
        if max_preview_bytes < 1 or max_entries < 1:
            raise ValueError("executor limits must be positive")
        self._max_preview_bytes = max_preview_bytes
        self._max_entries = max_entries

    async def execute(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        try:
            return await self._execute(session, call)
        except SandboxTimeout:
            return await self._failure(session, "error", "sandbox_timeout")
        except SandboxPolicyViolation:
            return await self._failure(
                session, "denied", "sandbox_policy_violation"
            )
        except (SandboxNotFound, FileNotFoundError):
            return await self._failure(session, "error", "sandbox_not_found")
        except SandboxError:
            return await self._failure(session, "error", "sandbox_error")

    async def _execute(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        if call.name == "read_file.v1":
            content = await session.read_file(str(call.input["path"]))
            return self._bounded_bytes(
                content, workspace_revision=await self._revision(session)
            )
        if call.name == "write_file.v1":
            revision = await session.write_file(
                str(call.input["path"]), str(call.input["content"]).encode()
            )
            return ToolResult.ok(workspace_revision=str(revision))
        return await self._dispatch_non_file_tool(session, call)

    async def _dispatch_non_file_tool(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        revision = await self._revision(session)
        if call.name == "list_tree.v1":
            entries = await session.list_tree(str(call.input["path"]))
            return self._entry_result(entries, revision)
        if call.name == "stat.v1":
            entry = await session.stat(str(call.input["path"]))
            return self._entry_result((entry,), revision)
        if call.name == "search_text.v1":
            matches = await session.search_text(
                str(call.input["query"]),
                paths=tuple(str(path) for path in call.input["paths"]),
                regex=bool(call.input["regex"]),
                limit=int(call.input["limit"]),
            )
            return self._entry_result(matches, revision)
        if call.name == "git_status.v1":
            return self._command_result(await session.git_status(), revision)
        if call.name == "git_diff.v1":
            result = await session.git_diff(staged=bool(call.input["staged"]))
            return self._command_result(result, revision)
        if call.name == "git_log.v1":
            result = await session.git_log(limit=int(call.input["limit"]))
            return self._command_result(result, revision)
        if call.name == "execute.v1":
            argv = tuple(str(value) for value in call.input["argv"])
            request = CommandRequest(
                argv=argv,
                cwd=str(call.input["cwd"]),
                env={str(key): str(value) for key, value in dict(call.input["env"]).items()},
                stdin=str(call.input["stdin"]).encode(),
                timeout_sec=float(call.input["timeout_sec"]),
                max_output_bytes=int(call.input["max_output_bytes"]),
            )
            result = await session.execute(request)
            return self._command_result(
                result,
                revision,
                audit={"executable_category": PurePosixPath(argv[0]).name},
            )
        return ToolResult(
            "denied", "unknown_tool", None, None, False, None, revision
        )

    def _bounded_bytes(self, content: bytes, *, workspace_revision: str) -> ToolResult:
        bounded = self._bytes_mapping(content)
        return ToolResult(
            status="ok",
            reason_code="ok",
            preview=str(bounded["preview"]),
            original_bytes=len(content),
            truncated=bool(bounded["truncated"]),
            checksum=str(bounded["checksum"]),
            workspace_revision=workspace_revision,
        )

    def _bytes_mapping(
        self, content: bytes, *, already_truncated: bool = False
    ) -> Mapping[str, object]:
        preview = content[: self._max_preview_bytes]
        return {
            "preview": preview.decode("utf-8", errors="replace"),
            "original_bytes": len(content),
            "truncated": already_truncated or len(content) > len(preview),
            "checksum": hashlib.sha256(content).hexdigest(),
        }

    def _entry_result(
        self,
        values: tuple[FileEntry, ...] | tuple[SearchMatch, ...],
        revision: str,
    ) -> ToolResult:
        entries = tuple(self._json_entry(value) for value in values[: self._max_entries])
        return ToolResult(
            "ok",
            "ok",
            None,
            None,
            len(values) > len(entries),
            None,
            revision,
            entries,
        )

    def _command_result(
        self,
        result: CommandResult,
        revision: str,
        *,
        audit: Mapping[str, object] | None = None,
    ) -> ToolResult:
        status: Literal["ok", "error", "denied"] = (
            "error" if result.timed_out else "ok"
        )
        reason = "sandbox_timeout" if result.timed_out else "ok"
        stdout = self._bytes_mapping(
            result.stdout, already_truncated=result.stdout_truncated
        )
        stderr = self._bytes_mapping(
            result.stderr, already_truncated=result.stderr_truncated
        )
        return ToolResult(
            status,
            reason,
            None,
            None,
            bool(stdout["truncated"]) or bool(stderr["truncated"]),
            None,
            revision,
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
            audit=audit,
        )

    async def _failure(
        self,
        session: SandboxSession,
        status: Literal["error", "denied"],
        reason: str,
    ) -> ToolResult:
        return ToolResult(
            status, reason, None, None, False, None, await self._revision(session)
        )

    async def _revision(self, session: SandboxSession) -> str:
        revision = getattr(session, "workspace_revision", 0)
        if callable(revision):
            revision = revision()
        if inspect.isawaitable(revision):
            revision = await revision
        return str(revision)

    @staticmethod
    def _json_entry(value: FileEntry | SearchMatch) -> Mapping[str, object]:
        raw = asdict(value)
        return {
            key: item.isoformat() if isinstance(item, datetime) else item
            for key, item in raw.items()
        }
