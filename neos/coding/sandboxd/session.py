"""`SandboxSession` over `neos-sandboxd`.

The session holds no workspace state of its own. Every call goes through a
`SandboxdAttachment`, which the managed provider implements: it checks the
durable ledger (owner digest, lifecycle state, generation), hands back a live
client for the **current** provider generation, and commits the revisions and
stream cursors the guest reports.

File operations re-resolve the attachment each time, so a session opened
before a suspend/resume keeps working afterwards. Streams (PTY, watcher) are
bound to the generation that created them: when the provider object is
replaced they close with `stream_generation_changed` instead of silently
reading another sandbox's journal.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TypeVar

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxStateConflict,
    SandboxUnavailable,
    SearchMatch,
    StreamEvent,
    read_byte_cap,
)
from neos.coding.sandbox.events import (
    PtyClosed,
    PtyEvent,
    PtyOutput,
    WorkspaceChange,
    WorkspaceChangeBatch,
    WorkspaceChangeKind,
)
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
)
from neos.coding.sandboxd.client import SandboxdClient

_GIT_SAFE = ("git", "--no-pager", "-c", "core.pager=cat")
_RESERVED_GUEST_ENV = frozenset({"PATH", "HOME", "TMPDIR"})
_POLL_WAIT_SEC = 1.0
_READ_PAGE = 256
_RECONNECT_ATTEMPTS = 3

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SandboxdLease:
    client: SandboxdClient
    limits: SandboxLimits
    generation: int


class SandboxdAttachment(Protocol):
    @property
    def sandbox_id(self) -> str: ...

    @property
    def allowed_env_names(self) -> frozenset[str]: ...

    @property
    def operation_timeout_sec(self) -> float: ...

    @property
    def max_pty_sessions(self) -> int: ...

    async def attach(self) -> SandboxdLease:
        """Verify ownership and RUNNING state; return the current client."""
        ...

    def mutation_lock(self) -> AbstractAsyncContextManager[Any]: ...

    async def commit_revision(self, revision: int, *, generation: int) -> None: ...

    async def current_generation(self) -> int | None: ...

    async def commit_stream_cursor(
        self, stream: str, cursor: int, *, generation: int
    ) -> None: ...


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: object) -> bytes:
    if not isinstance(value, str):
        raise SandboxUnavailable("sandboxd_response_invalid")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:
        raise SandboxUnavailable("sandboxd_response_invalid") from None


def _file_entry(value: object) -> FileEntry:
    try:
        return FileEntry(
            path=value["path"],  # type: ignore[index]
            kind=value["kind"],  # type: ignore[index]
            size=int(value["size"]),  # type: ignore[index]
            modified_at=datetime.fromisoformat(value["modified_at"]),  # type: ignore[index]
        )
    except (KeyError, TypeError, ValueError):
        raise SandboxUnavailable("sandboxd_response_invalid") from None


def _revision(result: Mapping[str, Any]) -> int:
    value = result.get("revision")
    if not isinstance(value, int) or value < 0:
        raise SandboxUnavailable("sandboxd_response_invalid")
    return value


class SandboxdSession:
    def __init__(self, attachment: SandboxdAttachment) -> None:
        self._attachment = attachment

    @property
    def sandbox_id(self) -> str:
        return self._attachment.sandbox_id

    async def _call(
        self, op: str, args: Mapping[str, Any], *, timeout_sec: float | None = None
    ) -> tuple[SandboxdLease, dict]:
        lease = await self._attachment.attach()
        result = await lease.client.call(
            op, args, timeout_sec=timeout_sec or self._attachment.operation_timeout_sec
        )
        return lease, result

    async def _mutate(self, op: str, args: Mapping[str, Any]) -> int:
        async with self._attachment.mutation_lock():
            lease, result = await self._call(op, args)
            revision = _revision(result)
            await self._attachment.commit_revision(revision, generation=lease.generation)
            return revision

    async def workspace_revision(self) -> int:
        lease, result = await self._call("revision", {})
        revision = _revision(result)
        await self._attachment.commit_revision(revision, generation=lease.generation)
        return revision

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        relative = normalize_workspace_path(path)
        _lease, result = await self._call("list_tree", {"path": relative.as_posix()})
        entries = result.get("entries")
        if not isinstance(entries, list):
            raise SandboxUnavailable("sandboxd_response_invalid")
        return tuple(_file_entry(entry) for entry in entries)

    async def stat(self, path: str) -> FileEntry:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = normalize_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
        _lease, result = await self._call("stat", {"path": relative.as_posix()})
        return _file_entry(result.get("entry"))

    async def read_file(
        self,
        path: str,
        *,
        offset: int = 1,
        limit: int | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        relative = normalize_workspace_path(path)
        if offset < 1 or (limit is not None and limit < 1):
            raise SandboxPolicyViolation("invalid_read_request")
        lease = await self._attachment.attach()
        cap = read_byte_cap(lease.limits.max_output_bytes, max_bytes)
        result = await lease.client.call(
            "read_file",
            {
                "path": relative.as_posix(),
                "offset": offset,
                "limit": limit,
                "max_bytes": cap,
            },
            timeout_sec=self._attachment.operation_timeout_sec,
        )
        return _unb64(result.get("data"))[:cap]

    async def write_file(
        self, path: str, content: bytes, *, parents: bool = True
    ) -> int:
        return await self._write(path, content, parents=parents, expected_revision=None)

    async def write_file_if_revision(
        self,
        path: str,
        content: bytes,
        *,
        expected_revision: int,
    ) -> int:
        # The compare happens inside the guest, under the workspace lock --
        # never here against a revision that may already be stale.
        return await self._write(
            path, content, parents=True, expected_revision=int(expected_revision)
        )

    async def _write(
        self,
        path: str,
        content: bytes,
        *,
        parents: bool,
        expected_revision: int | None,
    ) -> int:
        relative = ensure_mutable_workspace_path(path)
        lease = await self._attachment.attach()
        if len(content) > lease.limits.workspace_bytes:
            raise SandboxPolicyViolation("workspace_write_limit_exceeded")
        return await self._mutate(
            "write_file",
            {
                "path": relative.as_posix(),
                "data": _b64(content),
                "parents": parents,
                "expected_revision": expected_revision,
                "max_bytes": lease.limits.workspace_bytes,
            },
        )

    def _secret_guard(self, *paths: str) -> None:
        from neos.coding.domain.approvals import is_denied_secret_path

        if any(is_denied_secret_path(path) for path in paths):
            raise SandboxPolicyViolation("workspace_secret_path")

    async def mkdir(self, path: str, *, parents: bool = False) -> int:
        relative = ensure_mutable_workspace_path(path).as_posix()
        self._secret_guard(relative)
        return await self._mutate("mkdir", {"path": relative, "parents": parents})

    async def rm(self, path: str, *, recursive: bool = False) -> int:
        relative = ensure_mutable_workspace_path(path).as_posix()
        self._secret_guard(relative)
        return await self._mutate("rm", {"path": relative, "recursive": recursive})

    async def mv(self, src: str, dest: str, *, overwrite: bool = False) -> int:
        source = ensure_mutable_workspace_path(src).as_posix()
        target = ensure_mutable_workspace_path(dest).as_posix()
        self._secret_guard(source, target)
        return await self._mutate(
            "mv", {"src": source, "dest": target, "overwrite": overwrite}
        )

    async def chmod(self, path: str, mode: int) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path).as_posix()
        if is_denied_secret_path(relative) and mode & 0o002:
            raise SandboxPolicyViolation("workspace_secret_path")
        return await self._mutate("chmod", {"path": relative, "mode": int(mode)})

    async def search_text(
        self,
        query: str,
        *,
        paths: tuple[str, ...] = ("**/*",),
        regex: bool = False,
        limit: int = 100,
        before: int = 0,
        after: int = 0,
        output_mode: str = "content",
        ignore_case: bool = False,
        multiline: bool = False,
        context: int = 0,
        path: str | None = None,
        max_columns: int = 500,
        exclude: tuple[str, ...] = (),
    ) -> tuple[SearchMatch, ...]:
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        if context > 0:
            before = after = context
        for candidate in (*paths, *exclude):
            normalize_workspace_path(candidate)
        search_path = None if path is None else normalize_workspace_path(path).as_posix()
        lease = await self._attachment.attach()
        result = await lease.client.call(
            "search",
            {
                "query": query,
                "paths": list(paths),
                "regex": regex,
                "limit": limit,
                "before": before,
                "after": after,
                "output_mode": output_mode,
                "ignore_case": ignore_case,
                "multiline": multiline,
                "path": search_path,
                "max_columns": max_columns,
                "exclude": list(exclude),
                "max_file_bytes": lease.limits.max_output_bytes,
            },
            timeout_sec=self._attachment.operation_timeout_sec,
        )
        try:
            return tuple(
                SearchMatch(
                    path=value["path"],
                    line=value["line"],
                    column=value["column"],
                    text=value["text"],
                    before=tuple(value.get("before") or ()),
                    after=tuple(value.get("after") or ()),
                    count=value.get("count"),
                )
                for value in result["matches"]
            )
        except (KeyError, TypeError, AttributeError):
            raise SandboxUnavailable("sandboxd_response_invalid") from None

    async def glob_files(
        self,
        pattern: str,
        *,
        limit: int = 100,
        path: str | None = None,
    ) -> tuple[str, ...]:
        if not pattern or limit < 1:
            raise SandboxPolicyViolation("invalid_glob_request")
        normalize_workspace_path(pattern.replace("*", "x").replace("?", "x") or "x")
        start = None if path is None else normalize_workspace_path(path).as_posix()
        _lease, result = await self._call(
            "glob", {"pattern": pattern, "limit": limit, "path": start}
        )
        paths = result.get("paths")
        if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
            raise SandboxUnavailable("sandboxd_response_invalid")
        return tuple(paths)

    async def git_status(self) -> CommandResult:
        return await self.execute(
            CommandRequest(argv=(*_GIT_SAFE, "status", "--short", "--untracked-files=all"))
        )

    async def git_diff(self, *, staged: bool = False) -> CommandResult:
        argv = (
            (*_GIT_SAFE, "diff", "--cached", "--no-ext-diff")
            if staged
            else (*_GIT_SAFE, "diff", "--no-ext-diff")
        )
        return await self.execute(CommandRequest(argv=argv))

    async def git_log(self, *, limit: int = 20) -> CommandResult:
        if limit < 1 or limit > 100:
            raise SandboxPolicyViolation("git_log_limit_invalid")
        return await self.execute(
            CommandRequest(
                argv=(*_GIT_SAFE, "log", "--no-ext-diff", f"--max-count={limit}", "--oneline")
            )
        )

    async def execute(self, request: CommandRequest) -> CommandResult:
        disallowed = set(request.env) - self._attachment.allowed_env_names
        if disallowed:
            raise SandboxPolicyViolation("environment_not_allowed")
        cwd = normalize_workspace_path(request.cwd).as_posix()
        env = {
            key: value for key, value in request.env.items() if key not in _RESERVED_GUEST_ENV
        }
        async with self._attachment.mutation_lock():
            lease = await self._attachment.attach()
            limits = lease.limits
            if len(request.stdin) > limits.max_stdin_bytes:
                raise SandboxPolicyViolation("command_stdin_limit_exceeded")
            timeout = min(request.timeout_sec, limits.command_timeout_sec)
            result = await lease.client.call(
                "exec",
                {
                    "argv": list(request.argv),
                    "cwd": cwd,
                    "env": env,
                    "stdin": _b64(request.stdin),
                    "timeout_sec": timeout,
                    "max_output_bytes": min(request.max_output_bytes, limits.max_output_bytes),
                    "max_stdin_bytes": limits.max_stdin_bytes,
                },
                # The guest enforces the command deadline; the RPC deadline
                # only has to outlast it plus the workspace scans around it.
                timeout_sec=timeout + self._attachment.operation_timeout_sec,
            )
            await self._attachment.commit_revision(
                _revision(result), generation=lease.generation
            )
        exit_code = result.get("exit_code")
        if exit_code is not None and not isinstance(exit_code, int):
            raise SandboxUnavailable("sandboxd_response_invalid")
        return CommandResult(
            exit_code=exit_code,
            stdout=_unb64(result.get("stdout", "")),
            stderr=_unb64(result.get("stderr", "")),
            stdout_truncated=bool(result.get("stdout_truncated")),
            stderr_truncated=bool(result.get("stderr_truncated")),
            timed_out=bool(result.get("timed_out")),
        )

    # ---- PTY -------------------------------------------------------------

    async def create_pty(self, *, argv: tuple[str, ...]) -> SandboxdPty:
        CommandRequest(argv=argv)
        lease, result = await self._call(
            "pty.create",
            {"argv": list(argv), "max_sessions": self._attachment.max_pty_sessions},
        )
        pty_id = result.get("pty_id")
        if not isinstance(pty_id, str):
            raise SandboxUnavailable("sandboxd_response_invalid")
        return SandboxdPty(self._attachment, pty_id=pty_id, generation=lease.generation)

    async def write_pty(self, pty_id: str, data: bytes) -> None:
        lease = await self._attachment.attach()
        if len(data) > lease.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("pty_input_limit_exceeded")
        await lease.client.call(
            "pty.write",
            {"pty_id": pty_id, "data": _b64(data), "max_bytes": lease.limits.max_stdin_bytes},
            timeout_sec=self._attachment.operation_timeout_sec,
        )

    async def resize_pty(self, pty_id: str, *, rows: int, cols: int) -> None:
        await self._call("pty.resize", {"pty_id": pty_id, "rows": rows, "cols": cols})

    async def kill_pty(self, pty_id: str) -> None:
        await self._call("pty.kill", {"pty_id": pty_id})

    # ---- watcher ---------------------------------------------------------

    async def watch_files(self, *, after_cursor: int = 0) -> SandboxdWatcher:
        lease = await self._attachment.attach()
        watcher = SandboxdWatcher(
            self._attachment, generation=lease.generation, after_cursor=after_cursor
        )
        # Validate the cursor now: an evicted cursor must fail at open, the
        # same place the in-process watcher reports it.
        await watcher.replay(after_cursor=after_cursor)
        return watcher


class _JournalStream:
    """A cursor-addressed guest journal bound to one provider generation."""

    def __init__(
        self,
        attachment: SandboxdAttachment,
        *,
        stream: str,
        op: str,
        args: Mapping[str, Any],
        generation: int,
        decode: Callable[[Mapping[str, Any]], Any],
    ) -> None:
        self._attachment = attachment
        self._stream = stream
        self._op = op
        self._args = dict(args)
        self._generation = generation
        self._decode = decode
        self._closed = False

    async def _read(
        self, after_cursor: int, *, wait_sec: float
    ) -> tuple[tuple[StreamEvent[Any], ...], bool]:
        for attempt in range(_RECONNECT_ATTEMPTS):
            if self._closed:
                raise SandboxStateConflict("stream_closed")
            if await self._attachment.current_generation() != self._generation:
                self._closed = True
                raise SandboxStateConflict("stream_generation_changed")
            lease = await self._attachment.attach()
            if lease.generation != self._generation:
                self._closed = True
                raise SandboxStateConflict("stream_generation_changed")
            try:
                result = await lease.client.call(
                    self._op,
                    {
                        **self._args,
                        "after_cursor": after_cursor,
                        "wait_sec": wait_sec,
                        "max_events": _READ_PAGE,
                    },
                    timeout_sec=wait_sec + self._attachment.operation_timeout_sec,
                )
            except SandboxUnavailable as error:
                # E2B snapshots drop live connections while the guest keeps
                # running; reconnect and continue from the same cursor.
                if str(error) != "sandboxd_connection_lost" or attempt == _RECONNECT_ATTEMPTS - 1:
                    raise
                continue
            try:
                events = tuple(
                    StreamEvent(cursor=int(value["cursor"]), value=self._decode(value))
                    for value in result["events"]
                )
            except (KeyError, TypeError, ValueError):
                raise SandboxUnavailable("sandboxd_response_invalid") from None
            return events, bool(result.get("closed"))
        raise SandboxUnavailable("sandboxd_connection_lost")

    async def replay(self, *, after_cursor: int) -> tuple[StreamEvent[Any], ...]:
        collected: list[StreamEvent[Any]] = []
        cursor = after_cursor
        while True:
            events, _closed = await self._read(cursor, wait_sec=0)
            collected.extend(events)
            if len(events) < _READ_PAGE:
                return tuple(collected)
            cursor = events[-1].cursor

    async def subscribe(self, *, after_cursor: int) -> AsyncIterator[StreamEvent[Any]]:
        cursor = after_cursor
        while True:
            events, closed = await self._read(cursor, wait_sec=_POLL_WAIT_SEC)
            for event in events:
                yield event
                cursor = event.cursor
                await self._attachment.commit_stream_cursor(
                    self._stream, cursor, generation=self._generation
                )
            if closed:
                return

    async def close(self) -> None:
        self._closed = True


def _decode_pty(value: Mapping[str, Any]) -> PtyEvent:
    if value.get("kind") == "output":
        return PtyOutput(data=_unb64(value.get("data")))
    if value.get("kind") == "closed":
        exit_code = value.get("exit_code")
        return PtyClosed(
            reason=str(value.get("reason")),
            exit_code=exit_code if isinstance(exit_code, int) else None,
        )
    raise ValueError("unknown pty event")


def _decode_watch(value: Mapping[str, Any]) -> WorkspaceChangeBatch:
    return WorkspaceChangeBatch(
        changes=tuple(
            WorkspaceChange(path=str(change["path"]), kind=WorkspaceChangeKind(change["kind"]))
            for change in value["changes"]
        ),
        workspace_revision=int(value["revision"]),
    )


class SandboxdPty(_JournalStream):
    def __init__(
        self, attachment: SandboxdAttachment, *, pty_id: str, generation: int
    ) -> None:
        super().__init__(
            attachment,
            stream=f"pty:{pty_id}",
            op="pty.read",
            args={"pty_id": pty_id},
            generation=generation,
            decode=_decode_pty,
        )
        self.pty_id = pty_id


class SandboxdWatcher(_JournalStream):
    def __init__(
        self, attachment: SandboxdAttachment, *, generation: int, after_cursor: int
    ) -> None:
        super().__init__(
            attachment,
            stream="watch",
            op="watch.read",
            args={},
            generation=generation,
            decode=_decode_watch,
        )
        self._subscription: AsyncIterator[StreamEvent[Any]] | None = None
        self._after_cursor = after_cursor

    def __aiter__(self) -> SandboxdWatcher:
        return self

    async def __anext__(self) -> StreamEvent[WorkspaceChangeBatch]:
        if self._subscription is None:
            self._subscription = self.subscribe(after_cursor=self._after_cursor)
        return await anext(self._subscription)

    async def aclose(self) -> None:
        await self.close()
        subscription = self._subscription
        if subscription is not None:
            await subscription.aclose()  # type: ignore[attr-defined]


__all__ = [
    "SandboxdAttachment",
    "SandboxdLease",
    "SandboxdPty",
    "SandboxdSession",
    "SandboxdWatcher",
]
