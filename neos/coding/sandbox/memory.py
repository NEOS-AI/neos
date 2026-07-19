from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import pty
import re
import signal
import shutil
import struct
import termios
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TypeAlias

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    Sandbox,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
    SearchMatch,
    Snapshot,
    StreamEvent,
)
from neos.coding.sandbox.archive import (
    SNAPSHOT_SCHEMA_VERSION,
    LocalSnapshotStore,
    SnapshotManifest,
    create_workspace_archive,
    extract_workspace_archive,
    sha256_file,
)
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
    resolve_workspace_path,
)
from neos.coding.sandbox.process import BoundedProcessRunner
from neos.coding.sandbox.streams import BoundedReplayStream


@dataclass(frozen=True, slots=True)
class PtyOutput:
    data: bytes


@dataclass(frozen=True, slots=True)
class PtyClosed:
    reason: str
    exit_code: int | None


PtyEvent: TypeAlias = PtyOutput | PtyClosed


class WorkspaceChangeKind(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    WATCH_OVERFLOW = "watch_overflow"
    WORKSPACE_INVALIDATED = "workspace_invalidated"


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    path: str
    kind: WorkspaceChangeKind
    previous_path: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceChangeBatch:
    changes: tuple[WorkspaceChange, ...]
    workspace_revision: int


class MemoryWatcher:
    def __init__(
        self,
        stream: BoundedReplayStream[WorkspaceChangeBatch],
        *,
        after_cursor: int,
    ) -> None:
        self._stream = stream
        self._subscription = stream.subscribe(after_cursor=after_cursor)

    def __aiter__(self) -> MemoryWatcher:
        return self

    async def __anext__(self) -> StreamEvent[WorkspaceChangeBatch]:
        return await anext(self._subscription)

    async def replay(
        self,
        *,
        after_cursor: int,
    ) -> tuple[StreamEvent[WorkspaceChangeBatch], ...]:
        return await self._stream.replay(after_cursor=after_cursor)

    async def aclose(self) -> None:
        await self._subscription.aclose()


class _MemoryWatcherHub:
    def __init__(
        self,
        *,
        debounce_sec: float,
        replay_events: int,
    ) -> None:
        self._debounce_sec = debounce_sec
        self._stream = BoundedReplayStream[WorkspaceChangeBatch](
            max_events=replay_events,
            max_bytes=1024 * 1024,
            size_of=lambda batch: sum(
                len(change.path.encode()) + 32 for change in batch.changes
            ),
        )
        self._pending: dict[str, WorkspaceChange] = {}
        self._revision = 0
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def record(
        self,
        change: WorkspaceChange,
        *,
        revision: int,
    ) -> None:
        async with self._lock:
            previous = self._pending.get(change.path)
            if (
                previous is not None
                and previous.kind is WorkspaceChangeKind.CREATED
            ):
                change = previous
            self._pending[change.path] = change
            self._revision = revision
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = asyncio.create_task(self._flush_after_delay())

    def open(self, *, after_cursor: int) -> MemoryWatcher:
        return MemoryWatcher(self._stream, after_cursor=after_cursor)

    async def close(self) -> None:
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._flush()
        await self._stream.close()

    async def _flush_after_delay(self) -> None:
        await asyncio.sleep(self._debounce_sec)
        await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            batch = WorkspaceChangeBatch(
                changes=tuple(
                    self._pending[path] for path in sorted(self._pending)
                ),
                workspace_revision=self._revision,
            )
            self._pending.clear()
        await self._stream.publish(batch)


class MemoryPty:
    def __init__(
        self,
        *,
        pty_id: str,
        process: asyncio.subprocess.Process,
        master_fd: int,
        replay_events: int,
        replay_bytes: int,
    ) -> None:
        self.pty_id = pty_id
        self._process = process
        self._master_fd = master_fd
        self._stream = BoundedReplayStream[PtyEvent](
            max_events=replay_events,
            max_bytes=replay_bytes,
            size_of=lambda event: len(event.data)
            if isinstance(event, PtyOutput)
            else 32,
        )
        self._closed: asyncio.Future[PtyClosed] = (
            asyncio.get_running_loop().create_future()
        )
        self._requested_reason: str | None = None
        self._finish_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(
            self._read_output(),
            name=f"sandbox-pty-{pty_id}",
        )

    @property
    def is_closed(self) -> bool:
        return self._closed.done()

    def subscribe(self, *, after_cursor: int):
        return self._stream.subscribe(after_cursor=after_cursor)

    async def replay(
        self,
        *,
        after_cursor: int,
    ) -> tuple[StreamEvent[PtyEvent], ...]:
        return await self._stream.replay(after_cursor=after_cursor)

    async def write(self, data: bytes) -> None:
        if self.is_closed:
            raise SandboxStateConflict("pty_closed")
        await asyncio.to_thread(os.write, self._master_fd, data)

    async def resize(self, *, rows: int, cols: int) -> None:
        if rows < 1 or cols < 1 or rows > 1000 or cols > 1000:
            raise SandboxPolicyViolation("pty_size_invalid")
        fcntl.ioctl(
            self._master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    async def terminate(self, reason: str) -> PtyClosed:
        if self.is_closed:
            return await self._closed
        self._requested_reason = reason
        if self._process.returncode is None:
            try:
                os.killpg(self._process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await self._process.wait()
        await self._reader_task
        return await self._closed

    async def wait_closed(self) -> PtyClosed:
        return await self._closed

    async def _read_output(self) -> None:
        try:
            while True:
                data = await _read_pty_fd(self._master_fd)
                if not data:
                    break
                await self._stream.publish(PtyOutput(data=data))
        finally:
            await self._process.wait()
            await self._finish(
                self._requested_reason or "process_exited",
                None
                if self._requested_reason is not None
                else self._process.returncode,
            )

    async def _finish(
        self,
        reason: str,
        exit_code: int | None,
    ) -> None:
        async with self._finish_lock:
            if self._closed.done():
                return
            closed = PtyClosed(reason=reason, exit_code=exit_code)
            await self._stream.publish(closed)
            await self._stream.close()
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._closed.set_result(closed)


async def _read_pty_fd(fd: int) -> bytes:
    loop = asyncio.get_running_loop()
    ready: asyncio.Future[bytes] = loop.create_future()

    def read_ready() -> None:
        if ready.done():
            return
        try:
            ready.set_result(os.read(fd, 4096))
        except OSError as error:
            if error.errno == errno.EIO:
                ready.set_result(b"")
            else:
                ready.set_exception(error)

    loop.add_reader(fd, read_ready)
    try:
        return await ready
    finally:
        loop.remove_reader(fd)


@dataclass(slots=True)
class _MemorySandboxRecord:
    sandbox: Sandbox
    workspace: Path
    lock: asyncio.Lock
    ptys: dict[str, MemoryPty]
    watcher: _MemoryWatcherHub


class MemorySandboxProvider:
    """Executable reference sandbox backed by isolated local directories."""

    def __init__(
        self,
        *,
        root: Path,
        allowed_env_names: frozenset[str] = frozenset(
            {"HOME", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR"}
        ),
        process_runner: BoundedProcessRunner | None = None,
        snapshot_root: Path | None = None,
        max_pty_sessions: int = 4,
        pty_replay_events: int = 1024,
        pty_replay_bytes: int = 1024 * 1024,
        watcher_debounce_sec: float = 0.05,
        watcher_replay_events: int = 1024,
    ) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._allowed_env_names = allowed_env_names
        self._process_runner = process_runner or BoundedProcessRunner()
        self._snapshot_store = LocalSnapshotStore(
            snapshot_root or (self._root / "_snapshots")
        )
        self._max_pty_sessions = max_pty_sessions
        self._pty_replay_events = pty_replay_events
        self._pty_replay_bytes = pty_replay_bytes
        self._watcher_debounce_sec = watcher_debounce_sec
        self._watcher_replay_events = watcher_replay_events
        self._records: dict[str, _MemorySandboxRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        owner_id: str,
        limits: SandboxLimits,
    ) -> Sandbox:
        now = datetime.now(UTC)
        sandbox_id = f"sb_{uuid.uuid4().hex}"
        workspace = self._root / sandbox_id
        sandbox = Sandbox.creating(
            sandbox_id,
            owner_id,
            limits,
            now,
            provider="memory",
        )
        workspace.mkdir(mode=0o700)
        running = sandbox.transition(SandboxState.RUNNING, now)
        async with self._lock:
            self._records[sandbox_id] = _MemorySandboxRecord(
                sandbox=running,
                workspace=workspace,
                lock=asyncio.Lock(),
                ptys={},
                watcher=_MemoryWatcherHub(
                    debounce_sec=self._watcher_debounce_sec,
                    replay_events=self._watcher_replay_events,
                ),
            )
        return running

    async def get(self, sandbox_id: str) -> Sandbox:
        return (await self._record(sandbox_id)).sandbox

    async def open_session(self, sandbox_id: str) -> MemorySandboxSession:
        record = await self._running_record(sandbox_id)
        return MemorySandboxSession(self, record)

    async def suspend(self, sandbox_id: str) -> Sandbox:
        record = await self._record(sandbox_id)
        async with record.lock:
            await self._terminate_ptys(record, "sandbox_suspended")
            record.sandbox = record.sandbox.transition(
                SandboxState.SUSPENDED,
                datetime.now(UTC),
            )
            return record.sandbox

    async def resume(self, sandbox_id: str) -> Sandbox:
        record = await self._record(sandbox_id)
        async with record.lock:
            record.sandbox = record.sandbox.transition(
                SandboxState.RUNNING,
                datetime.now(UTC),
            )
            return record.sandbox

    async def snapshot(self, sandbox_id: str) -> Snapshot:
        record = await self._record(sandbox_id)
        if record.sandbox.state not in {
            SandboxState.RUNNING,
            SandboxState.SUSPENDED,
        }:
            raise SandboxStateConflict(
                f"sandbox_{record.sandbox.state.value}"
            )
        async with record.lock:
            snapshot_id = f"ss_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC)
            archive_path = self._snapshot_store.archive_path(snapshot_id)
            checksum = await asyncio.to_thread(
                create_workspace_archive,
                record.workspace,
                archive_path,
                max_archive_bytes=record.sandbox.limits.workspace_bytes,
            )
            manifest = SnapshotManifest(
                schema_version=SNAPSHOT_SCHEMA_VERSION,
                source_sandbox_id=sandbox_id,
                workspace_revision=record.sandbox.workspace_revision,
                created_at=created_at,
                base_image_digest=record.sandbox.image_digest,
                content_checksum=checksum,
            )
            await asyncio.to_thread(
                self._snapshot_store.save_manifest,
                snapshot_id,
                manifest,
            )
            return Snapshot(
                snapshot_id=snapshot_id,
                source_sandbox_id=sandbox_id,
                workspace_revision=manifest.workspace_revision,
                created_at=created_at,
                content_checksum=checksum,
                image_digest=manifest.base_image_digest,
            )

    async def restore(self, snapshot_id: str, *, owner_id: str) -> Sandbox:
        manifest = await asyncio.to_thread(
            self._snapshot_store.load_manifest,
            snapshot_id,
        )
        if manifest.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise SandboxPolicyViolation("snapshot_schema_incompatible")
        archive_path = self._snapshot_store.archive_path(snapshot_id)
        actual_checksum = await asyncio.to_thread(sha256_file, archive_path)
        if actual_checksum != manifest.content_checksum:
            raise SandboxPolicyViolation("snapshot_checksum_mismatch")

        restored: Sandbox | None = None
        complete = False
        try:
            restored = await self.create(
                owner_id=owner_id,
                limits=SandboxLimits.safe_defaults(),
            )
            record = await self._record(restored.sandbox_id)
            async with record.lock:
                await asyncio.to_thread(
                    extract_workspace_archive,
                    archive_path,
                    record.workspace,
                    max_expanded_bytes=record.sandbox.limits.workspace_bytes,
                )
                record.sandbox = replace(
                    record.sandbox,
                    workspace_revision=manifest.workspace_revision,
                    updated_at=datetime.now(UTC),
                )
                complete = True
                return record.sandbox
        finally:
            if restored is not None and not complete:
                await self.destroy(restored.sandbox_id)

    async def destroy(self, sandbox_id: str) -> None:
        async with self._lock:
            record = self._records.pop(sandbox_id, None)
        if record is None:
            return
        async with record.lock:
            await self._terminate_ptys(record, "sandbox_destroyed")
            await record.watcher.close()
            record.sandbox = record.sandbox.transition(
                SandboxState.DESTROYED,
                datetime.now(UTC),
            )
            shutil.rmtree(record.workspace, ignore_errors=True)

    async def close(self) -> None:
        async with self._lock:
            sandbox_ids = tuple(self._records)
        for sandbox_id in sandbox_ids:
            await self.destroy(sandbox_id)

    def workspace_path(self, sandbox_id: str) -> Path:
        record = self._records.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        return record.workspace

    def snapshot_archive_path(self, snapshot_id: str) -> Path:
        return self._snapshot_store.archive_path(snapshot_id)

    async def _record(self, sandbox_id: str) -> _MemorySandboxRecord:
        async with self._lock:
            record = self._records.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        return record

    async def _running_record(
        self,
        sandbox_id: str,
    ) -> _MemorySandboxRecord:
        record = await self._record(sandbox_id)
        if record.sandbox.state is not SandboxState.RUNNING:
            raise SandboxStateConflict(
                f"sandbox_{record.sandbox.state.value}"
            )
        return record

    async def _increment_revision(
        self,
        record: _MemorySandboxRecord,
    ) -> int:
        record.sandbox = replace(
            record.sandbox,
            workspace_revision=record.sandbox.workspace_revision + 1,
            updated_at=datetime.now(UTC),
        )
        return record.sandbox.workspace_revision

    @staticmethod
    async def _terminate_ptys(
        record: _MemorySandboxRecord,
        reason: str,
    ) -> None:
        for terminal in tuple(record.ptys.values()):
            await terminal.terminate(reason)
        record.ptys.clear()


class MemorySandboxSession:
    def __init__(
        self,
        provider: MemorySandboxProvider,
        record: _MemorySandboxRecord,
    ) -> None:
        self._provider = provider
        self._record = record

    @property
    def sandbox_id(self) -> str:
        return self._record.sandbox.sandbox_id

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        await self._require_running()
        root = resolve_workspace_path(self._record.workspace, path)
        entries = []
        for item in sorted(root.rglob("*")):
            if item.is_symlink():
                kind = "symlink"
            elif item.is_dir():
                kind = "directory"
            else:
                kind = "file"
            stat = item.lstat()
            entries.append(
                FileEntry(
                    path=item.relative_to(self._record.workspace).as_posix(),
                    kind=kind,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=UTC,
                    ),
                )
            )
        return tuple(entries)

    async def stat(self, path: str) -> FileEntry:
        await self._require_running()
        item = resolve_workspace_path(self._record.workspace, path)
        value = item.lstat()
        kind = "symlink" if item.is_symlink() else (
            "directory" if item.is_dir() else "file"
        )
        return FileEntry(
            path=item.relative_to(self._record.workspace).as_posix(),
            kind=kind,
            size=value.st_size,
            modified_at=datetime.fromtimestamp(value.st_mtime, tz=UTC),
        )

    async def read_file(self, path: str) -> bytes:
        await self._require_running()
        item = resolve_workspace_path(self._record.workspace, path)
        if not item.is_file():
            raise SandboxPolicyViolation("workspace_path_is_not_file")
        if item.stat().st_size > self._record.sandbox.limits.max_output_bytes:
            raise SandboxPolicyViolation("file_read_limit_exceeded")
        return await asyncio.to_thread(item.read_bytes)

    async def write_file(self, path: str, content: bytes) -> int:
        await self._require_running()
        if len(content) > self._record.sandbox.limits.workspace_bytes:
            raise SandboxPolicyViolation("workspace_write_limit_exceeded")
        relative = ensure_mutable_workspace_path(path)
        async with self._record.lock:
            await self._require_running()
            self._create_safe_parents(relative.parent)
            item = resolve_workspace_path(
                self._record.workspace,
                relative.as_posix(),
                allow_missing_leaf=True,
            )
            existed = item.exists()
            await asyncio.to_thread(item.write_bytes, content)
            revision = await self._provider._increment_revision(self._record)
            await self._record.watcher.record(
                WorkspaceChange(
                    path=relative.as_posix(),
                    kind=(
                        WorkspaceChangeKind.MODIFIED
                        if existed
                        else WorkspaceChangeKind.CREATED
                    ),
                ),
                revision=revision,
            )
            return revision

    async def search_text(
        self,
        query: str,
        *,
        paths: tuple[str, ...] = ("**/*",),
        regex: bool = False,
        limit: int = 100,
    ) -> tuple[SearchMatch, ...]:
        await self._require_running()
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        expression = re.compile(query if regex else re.escape(query))
        matches: list[SearchMatch] = []
        for item in sorted(self._record.workspace.rglob("*")):
            if not item.is_file() or item.is_symlink():
                continue
            relative = item.relative_to(self._record.workspace).as_posix()
            if not any(self._matches_path(relative, pattern) for pattern in paths):
                continue
            try:
                text = item.read_text(errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = expression.search(line)
                if match is None:
                    continue
                matches.append(
                    SearchMatch(
                        path=relative,
                        line=line_number,
                        column=match.start() + 1,
                        text=line,
                    )
                )
                if len(matches) >= limit:
                    return tuple(matches)
        return tuple(matches)

    async def git_status(self) -> CommandResult:
        return await self.execute(
            CommandRequest(
                argv=("git", "status", "--short", "--untracked-files=all")
            )
        )

    async def git_diff(self, *, staged: bool = False) -> CommandResult:
        argv = ("git", "diff", "--cached") if staged else ("git", "diff")
        return await self.execute(CommandRequest(argv=argv))

    async def git_log(self, *, limit: int = 20) -> CommandResult:
        if limit < 1 or limit > 100:
            raise SandboxPolicyViolation("git_log_limit_invalid")
        return await self.execute(
            CommandRequest(
                argv=("git", "log", f"--max-count={limit}", "--oneline")
            )
        )

    async def execute(self, request: CommandRequest) -> CommandResult:
        await self._require_running()
        disallowed = set(request.env) - self._provider._allowed_env_names
        if disallowed:
            raise SandboxPolicyViolation("environment_not_allowed")
        if len(request.stdin) > self._record.sandbox.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("command_stdin_limit_exceeded")
        cwd = resolve_workspace_path(self._record.workspace, request.cwd)
        if not cwd.is_dir():
            raise SandboxPolicyViolation("command_cwd_is_not_directory")
        bounded_request = replace(
            request,
            timeout_sec=min(
                request.timeout_sec,
                self._record.sandbox.limits.command_timeout_sec,
            ),
            max_output_bytes=min(
                request.max_output_bytes,
                self._record.sandbox.limits.max_output_bytes,
            ),
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in self._provider._allowed_env_names
        }
        environment.update(request.env)
        async with self._record.lock:
            await self._require_running()
            before = self._workspace_fingerprint()
            result = await self._provider._process_runner.run(
                bounded_request,
                cwd=cwd,
                env=environment,
            )
            after = self._workspace_fingerprint()
            changes = self._fingerprint_changes(before, after)
            if changes:
                revision = await self._provider._increment_revision(
                    self._record
                )
                for change in changes:
                    await self._record.watcher.record(
                        change,
                        revision=revision,
                    )
            return result

    async def create_pty(self, *, argv: tuple[str, ...]) -> MemoryPty:
        await self._require_running()
        CommandRequest(argv=argv)
        active = [
            terminal
            for terminal in self._record.ptys.values()
            if not terminal.is_closed
        ]
        if len(active) >= self._provider._max_pty_sessions:
            raise SandboxPolicyViolation("pty_session_limit_exceeded")
        master_fd, slave_fd = pty.openpty()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in self._provider._allowed_env_names
        }
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self._record.workspace,
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        except BaseException:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        pty_id = f"pty_{uuid.uuid4().hex}"
        terminal = MemoryPty(
            pty_id=pty_id,
            process=process,
            master_fd=master_fd,
            replay_events=self._provider._pty_replay_events,
            replay_bytes=self._provider._pty_replay_bytes,
        )
        self._record.ptys[pty_id] = terminal
        return terminal

    async def write_pty(self, pty_id: str, data: bytes) -> None:
        await self._require_running()
        if len(data) > self._record.sandbox.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("pty_input_limit_exceeded")
        await self._pty(pty_id).write(data)

    async def resize_pty(
        self,
        pty_id: str,
        *,
        rows: int,
        cols: int,
    ) -> None:
        await self._require_running()
        await self._pty(pty_id).resize(rows=rows, cols=cols)

    async def kill_pty(self, pty_id: str) -> None:
        await self._pty(pty_id).terminate("killed")
        self._record.ptys.pop(pty_id, None)

    async def watch_files(
        self,
        *,
        after_cursor: int = 0,
    ) -> MemoryWatcher:
        await self._require_running()
        return self._record.watcher.open(after_cursor=after_cursor)

    async def _require_running(self) -> None:
        await self._provider._running_record(self.sandbox_id)

    def _create_safe_parents(self, parent: PurePosixPath) -> None:
        current = PurePosixPath(".")
        for part in parent.parts:
            current /= part
            candidate = resolve_workspace_path(
                self._record.workspace,
                current.as_posix(),
                allow_missing_leaf=True,
            )
            candidate.mkdir(exist_ok=True)

    def _pty(self, pty_id: str) -> MemoryPty:
        terminal = self._record.ptys.get(pty_id)
        if terminal is None:
            raise SandboxNotFound(pty_id)
        return terminal

    def _workspace_fingerprint(self) -> dict[str, tuple[int, int]]:
        fingerprint: dict[str, tuple[int, int]] = {}
        for item in self._record.workspace.rglob("*"):
            if not item.is_file() or item.is_symlink():
                continue
            relative = item.relative_to(self._record.workspace).as_posix()
            if self._ignore_watch_path(relative):
                continue
            value = item.stat()
            fingerprint[relative] = (value.st_size, value.st_mtime_ns)
        return fingerprint

    @staticmethod
    def _fingerprint_changes(
        before: dict[str, tuple[int, int]],
        after: dict[str, tuple[int, int]],
    ) -> tuple[WorkspaceChange, ...]:
        changes = [
            WorkspaceChange(path=path, kind=WorkspaceChangeKind.CREATED)
            for path in sorted(after.keys() - before.keys())
        ]
        changes.extend(
            WorkspaceChange(path=path, kind=WorkspaceChangeKind.MODIFIED)
            for path in sorted(before.keys() & after.keys())
            if before[path] != after[path]
        )
        changes.extend(
            WorkspaceChange(path=path, kind=WorkspaceChangeKind.DELETED)
            for path in sorted(before.keys() - after.keys())
        )
        return tuple(changes)

    @staticmethod
    def _ignore_watch_path(path: str) -> bool:
        name = PurePosixPath(path).name
        return (
            path == ".git"
            or path.startswith(".git/")
            or name == ".DS_Store"
            or name.endswith((".swp", ".swo", "~"))
        )

    @staticmethod
    def _matches_path(path: str, pattern: str) -> bool:
        normalized = normalize_workspace_path(pattern).as_posix()
        if normalized.endswith("/**"):
            return path.startswith(normalized[:-3].rstrip("/") + "/")
        return PurePosixPath(path).match(normalized)
