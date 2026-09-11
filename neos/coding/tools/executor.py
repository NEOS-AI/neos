from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
_ALLOWED_SKILLS = frozenset({"verify", "commit"})

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
from neos.coding.sandbox.observability import bounded_executable_category
from neos.coding.sandbox.paths import normalize_workspace_path
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
    def ok(
        cls,
        *,
        workspace_revision: str,
        entries: tuple[Mapping[str, object], ...] = (),
    ) -> ToolResult:
        return cls("ok", "ok", None, None, False, None, workspace_revision, entries)

    def to_mapping(self) -> Mapping[str, object]:
        return asdict(self)


class SandboxToolExecutor:
    def __init__(self, max_preview_bytes: int, max_entries: int) -> None:
        if max_preview_bytes < 1 or max_entries < 1:
            raise ValueError("executor limits must be positive")
        self._max_preview_bytes = max_preview_bytes
        self._max_entries = max_entries
        self._read_paths: dict[str, set[str]] = {}

    async def execute(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str] = frozenset(),
    ) -> ToolResult:
        try:
            return await self._execute(session, call, known_reads=known_reads)
        except SandboxTimeout:
            return self._failure("error", "sandbox_timeout")
        except SandboxPolicyViolation:
            return self._failure("denied", "sandbox_policy_violation")
        except (SandboxNotFound, FileNotFoundError):
            return self._failure("error", "sandbox_not_found")
        except SandboxError:
            return self._failure("error", "sandbox_error")

    async def _execute(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        if call.name == "read_file.v1":
            return await self._read_file(session, call)
        if call.name == "write_file.v1":
            return await self._write_file(session, call, known_reads=known_reads)
        if call.name == "edit_file.v1":
            return await self._edit_file(session, call, known_reads=known_reads)
        return await self._dispatch_non_file_tool(session, call)

    async def _read_file(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        path = str(call.input["path"])
        offset = int(call.input.get("offset", 1))
        raw_limit = call.input.get("limit")
        limit = int(raw_limit) if raw_limit is not None else None
        content = await session.read_file(path)
        lines = content.decode("utf-8", errors="replace").splitlines(keepends=True)
        start = max(offset - 1, 0)
        end = None if limit is None else start + limit
        sliced = lines[start:end]
        omitted = start > 0 or (end is not None and end < len(lines))
        numbered = "".join(
            f"{number:>6}|{line}" for number, line in enumerate(sliced, start=offset)
        )
        result = self._bounded_bytes(
            numbered.encode("utf-8"),
            workspace_revision=await self._revision(session),
            already_truncated=omitted,
            original_bytes=len(content),
        )
        self._mark_read(session, path)
        return result

    async def _write_file(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        path = str(call.input["path"])
        denied = await self._deny_unread_existing(
            session, path, known_reads=known_reads
        )
        if denied is not None:
            return denied
        revision = await session.write_file(
            path, str(call.input["content"]).encode()
        )
        return ToolResult.ok(workspace_revision=str(revision))

    async def _edit_file(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        path = str(call.input["path"])
        denied = await self._deny_unread_existing(
            session, path, known_reads=known_reads
        )
        if denied is not None:
            return denied
        content = await session.read_file(path)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return await self._denied(session, "edit_not_text")
        old_string = str(call.input["old_string"])
        new_string = str(call.input["new_string"])
        replace_all = bool(call.input.get("replace_all", False))
        matches = text.count(old_string)
        if matches == 0:
            return await self._denied(session, "edit_old_string_not_found")
        if matches > 1 and not replace_all:
            return await self._denied(session, "edit_old_string_not_unique")
        updated = (
            text.replace(old_string, new_string)
            if replace_all
            else text.replace(old_string, new_string, 1)
        )
        revision = await session.write_file(path, updated.encode("utf-8"))
        return ToolResult.ok(workspace_revision=str(revision))

    async def _deny_unread_existing(
        self,
        session: SandboxSession,
        path: str,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult | None:
        if not await self._path_exists(session, path):
            return None
        if self._was_read(session, path, known_reads=known_reads):
            return None
        return await self._denied(session, "precondition_read_required")

    async def _path_exists(self, session: SandboxSession, path: str) -> bool:
        try:
            await session.stat(path)
        except (SandboxNotFound, FileNotFoundError):
            return False
        except SandboxPolicyViolation as error:
            if str(error) == "workspace_path_not_resolvable":
                return False
            raise
        return True

    def _mark_read(self, session: SandboxSession, path: str) -> None:
        self._read_paths.setdefault(session.sandbox_id, set()).add(
            str(normalize_workspace_path(path))
        )

    def _was_read(
        self,
        session: SandboxSession,
        path: str,
        *,
        known_reads: frozenset[str],
    ) -> bool:
        normalized = str(normalize_workspace_path(path))
        if normalized in known_reads:
            return True
        recorded = self._read_paths.get(session.sandbox_id, set())
        return normalized in recorded

    async def _denied(self, session: SandboxSession, reason: str) -> ToolResult:
        return ToolResult(
            "denied",
            reason,
            None,
            None,
            False,
            None,
            await self._revision(session),
        )

    async def _dispatch_non_file_tool(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        if call.name == "todo_write.v1":
            return self._todo_write(call)
        if call.name == "set_phase.v1":
            return self._set_phase(call)
        if call.name == "ask_user.v1":
            return self._ask_user(call)
        if call.name == "load_skill.v1":
            return self._load_skill(call)
        if call.name == "list_tree.v1":
            entries = await session.list_tree(str(call.input["path"]))
            return self._entry_result(entries, await self._revision(session))
        if call.name == "stat.v1":
            entry = await session.stat(str(call.input["path"]))
            return self._entry_result((entry,), await self._revision(session))
        if call.name == "search_text.v1":
            matches = await session.search_text(
                str(call.input["query"]),
                paths=tuple(str(path) for path in call.input["paths"]),
                regex=bool(call.input["regex"]),
                limit=int(call.input["limit"]),
            )
            return self._entry_result(matches, await self._revision(session))
        if call.name == "git_status.v1":
            result = await session.git_status()
            return self._command_result(result, await self._revision(session))
        if call.name == "git_diff.v1":
            result = await session.git_diff(staged=bool(call.input["staged"]))
            return self._command_result(result, await self._revision(session))
        if call.name == "git_log.v1":
            result = await session.git_log(limit=int(call.input["limit"]))
            return self._command_result(result, await self._revision(session))
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
                await self._revision(session),
                audit={"executable_category": bounded_executable_category(argv[0])},
            )
        return ToolResult(
            "denied",
            "unknown_tool",
            None,
            None,
            False,
            None,
            await self._revision(session),
        )

    @staticmethod
    def _todo_write(call: ValidatedToolCall) -> ToolResult:
        entries = tuple(dict(item) for item in call.input["todos"])
        return ToolResult.ok(workspace_revision="unknown", entries=entries)

    @staticmethod
    def _set_phase(call: ValidatedToolCall) -> ToolResult:
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"phase": str(call.input["phase"])},),
        )

    @staticmethod
    def _ask_user(call: ValidatedToolCall) -> ToolResult:
        questions = [str(item) for item in call.input["questions"]]
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"questions": questions},),
        )

    @staticmethod
    def _load_skill(call: ValidatedToolCall) -> ToolResult:
        name = str(call.input.get("name", ""))
        if name not in _ALLOWED_SKILLS:
            return ToolResult(
                "denied", "unknown_skill", None, None, False, None, "unknown"
            )
        path = _SKILLS_DIR / f"{name}.md"
        if not path.is_file():
            return ToolResult(
                "denied", "unknown_skill", None, None, False, None, "unknown"
            )
        markdown = path.read_text(encoding="utf-8")
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"name": name, "markdown": markdown},),
        )

    def _bounded_bytes(
        self,
        content: bytes,
        *,
        workspace_revision: str,
        already_truncated: bool = False,
        original_bytes: int | None = None,
    ) -> ToolResult:
        bounded = self._bytes_mapping(content, already_truncated=already_truncated)
        return ToolResult(
            status="ok",
            reason_code="ok",
            preview=str(bounded["preview"]),
            original_bytes=len(content) if original_bytes is None else original_bytes,
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
        failed = result.timed_out or result.exit_code not in {0, None}
        status: Literal["ok", "error", "denied"] = "error" if failed else "ok"
        reason = (
            "sandbox_timeout"
            if result.timed_out
            else "command_failed"
            if result.exit_code not in {0, None}
            else "ok"
        )
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

    @staticmethod
    def _failure(
        status: Literal["error", "denied"],
        reason: str,
    ) -> ToolResult:
        return ToolResult(
            status, reason, None, None, False, None, "unknown"
        )

    async def _revision(self, session: SandboxSession) -> str:
        return str(await session.workspace_revision())

    @staticmethod
    def _json_entry(value: FileEntry | SearchMatch) -> Mapping[str, object]:
        raw = asdict(value)
        return {
            key: item.isoformat() if isinstance(item, datetime) else item
            for key, item in raw.items()
        }
