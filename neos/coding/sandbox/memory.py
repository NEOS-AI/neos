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
import tempfile
import termios
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

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
    resolve_mutable_workspace_path,
    resolve_workspace_path,
)
from neos.coding.sandbox.process import BoundedProcessRunner
from neos.coding.sandbox.streams import BoundedReplayStream
from neos.coding.sandbox.events import (
    PtyClosed,
    PtyEvent,
    PtyOutput,
    SandboxWatcher as MemoryWatcher,
    SandboxWatcherHub as _MemoryWatcherHub,
    WorkspaceChange,
    WorkspaceChangeKind,
)
from neos.coding.sandbox.ignore import (
    iter_workspace_files,
    load_ignore_rules,
    should_skip_walk,
)

_GIT_SAFE = ("git", "--no-pager", "-c", "core.pager=cat")


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


def _write_atomic_bytes(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=".neos-write-",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


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

    async def workspace_revision(self) -> int:
        await self._require_running()
        return self._record.sandbox.workspace_revision

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        await self._require_running()
        root = resolve_workspace_path(self._record.workspace, path)
        if not root.is_dir() or root.is_symlink():
            return ()
        rules = load_ignore_rules(self._record.workspace)
        entries: list[FileEntry] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            kept: list[str] = []
            for name in dirnames:
                item = current / name
                relative = item.relative_to(self._record.workspace).as_posix()
                if should_skip_walk(relative, rules=rules, is_dir=True):
                    continue
                kept.append(name)
                entries.append(self._file_entry(item))
            dirnames[:] = kept
            for name in filenames:
                item = current / name
                relative = item.relative_to(self._record.workspace).as_posix()
                if should_skip_walk(relative, rules=rules, is_dir=False):
                    continue
                entries.append(self._file_entry(item))
        entries.sort(key=lambda entry: entry.path)
        return tuple(entries)

    def _file_entry(self, item: Path) -> FileEntry:
        if item.is_symlink():
            kind = "symlink"
        elif item.is_dir():
            kind = "directory"
        else:
            kind = "file"
        stat = item.lstat()
        return FileEntry(
            path=item.relative_to(self._record.workspace).as_posix(),
            kind=kind,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

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

    async def read_file(
        self,
        path: str,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> bytes:
        await self._require_running()
        item = resolve_workspace_path(self._record.workspace, path)
        if not item.is_file():
            raise SandboxPolicyViolation("workspace_path_is_not_file")
        if offset < 1 or (limit is not None and limit < 1):
            raise SandboxPolicyViolation("invalid_read_request")
        max_bytes = self._record.sandbox.limits.max_output_bytes
        if limit is None:
            if item.stat().st_size > max_bytes:
                raise SandboxPolicyViolation("file_read_limit_exceeded")
            return await asyncio.to_thread(item.read_bytes)
        return await asyncio.to_thread(
            _read_file_range, item, offset, limit, max_bytes
        )

    async def write_file(
        self, path: str, content: bytes, *, parents: bool = True
    ) -> int:
        return await self._write_file(
            path, content, expected_revision=None, parents=parents
        )

    async def write_file_if_revision(
        self,
        path: str,
        content: bytes,
        *,
        expected_revision: int,
    ) -> int:
        return await self._write_file(
            path,
            content,
            expected_revision=expected_revision,
        )

    async def _write_file(
        self,
        path: str,
        content: bytes,
        *,
        expected_revision: int | None,
        parents: bool = True,
    ) -> int:
        await self._require_running()
        if len(content) > self._record.sandbox.limits.workspace_bytes:
            raise SandboxPolicyViolation("workspace_write_limit_exceeded")
        relative = ensure_mutable_workspace_path(path)
        async with self._record.lock:
            await self._require_running()
            if (
                expected_revision is not None
                and self._record.sandbox.workspace_revision
                != expected_revision
            ):
                raise SandboxStateConflict("workspace_revision_conflict")
            if parents:
                self._create_safe_parents(relative.parent)
            item = resolve_mutable_workspace_path(
                self._record.workspace,
                relative.as_posix(),
            )
            existed = item.exists()
            await asyncio.to_thread(_write_atomic_bytes, item, content)
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
        before: int = 0,
        after: int = 0,
        output_mode: str = "content",
        ignore_case: bool = False,
        multiline: bool = False,
        context: int = 0,
        path: str | None = None,
        max_columns: int = 500,
    ) -> tuple[SearchMatch, ...]:
        await self._require_running()
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        if output_mode not in {"files", "content", "count"}:
            output_mode = "content"
        if context > 0:
            before = after = context
        before = max(0, min(int(before), 20))
        after = max(0, min(int(after), 20))
        flags = 0
        if ignore_case:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.DOTALL
        expression = re.compile(query if regex else re.escape(query), flags)
        workspace = self._record.workspace
        start = (
            resolve_workspace_path(workspace, path)
            if path is not None
            else workspace
        )
        rules = load_ignore_rules(workspace)
        matches: list[SearchMatch] = []
        for item, relative in iter_workspace_files(
            workspace, root=start, rules=rules
        ):
            if not any(self._matches_path(relative, pattern) for pattern in paths):
                continue
            if _file_is_binary(item):
                continue
            try:
                text = item.read_text(errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            if multiline:
                file_hits = 0
                for match in expression.finditer(text):
                    file_hits += 1
                    if output_mode != "content":
                        continue
                    line_number = text.count("\n", 0, match.start()) + 1
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.start())
                    if line_end < 0:
                        line_end = len(text)
                    line = text[line_start:line_end].rstrip("\r")
                    matches.append(
                        _search_match(
                            relative,
                            line_number,
                            match.start() - line_start + 1,
                            line,
                            lines,
                            before,
                            after,
                            max_columns,
                        )
                    )
                    if len(matches) >= limit:
                        return tuple(matches)
                if file_hits == 0 or output_mode == "content":
                    continue
            else:
                file_hits = 0
                for line_number, line in enumerate(lines, start=1):
                    match = expression.search(line)
                    if match is None:
                        continue
                    file_hits += 1
                    if output_mode != "content":
                        continue
                    matches.append(
                        _search_match(
                            relative,
                            line_number,
                            match.start() + 1,
                            line,
                            lines,
                            before,
                            after,
                            max_columns,
                        )
                    )
                    if len(matches) >= limit:
                        return tuple(matches)
                if file_hits == 0 or output_mode == "content":
                    continue
            if output_mode == "files":
                matches.append(
                    SearchMatch(path=relative, line=0, column=0, text="")
                )
            else:
                matches.append(
                    SearchMatch(
                        path=relative,
                        line=0,
                        column=0,
                        text="",
                        count=file_hits,
                    )
                )
            if len(matches) >= limit:
                return tuple(matches)
        return tuple(matches)

    async def glob_files(self, pattern: str, *, limit: int = 100) -> tuple[str, ...]:
        await self._require_running()
        from neos.coding.sandbox.paths import normalize_workspace_path

        if not pattern or limit < 1:
            raise SandboxPolicyViolation("invalid_glob_request")
        normalize_workspace_path(pattern.replace("*", "x").replace("?", "x") or "x")
        # Keep lex path order; mtime sort would break existing glob assertions.
        found: list[str] = []
        rules = load_ignore_rules(self._record.workspace)
        for _item, relative in iter_workspace_files(
            self._record.workspace, rules=rules
        ):
            if self._matches_path(relative, pattern):
                found.append(relative)
                if len(found) >= limit:
                    break
        return tuple(found)

    async def git_status(self) -> CommandResult:
        return await self.execute(
            CommandRequest(
                argv=(
                    *_GIT_SAFE,
                    "status",
                    "--short",
                    "--untracked-files=all",
                )
            )
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
                argv=(
                    *_GIT_SAFE,
                    "log",
                    "--no-ext-diff",
                    f"--max-count={limit}",
                    "--oneline",
                )
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
            if part == ".":
                continue
            current /= part
            candidate = self._record.workspace.joinpath(*current.parts)
            if candidate.is_symlink():
                raise SandboxPolicyViolation("workspace_symlink_parent")
            if not candidate.exists():
                candidate.mkdir(exist_ok=True)
            if candidate.is_symlink():
                raise SandboxPolicyViolation("workspace_symlink_parent")

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
    def _is_git_path(path: str) -> bool:
        return ".git" in PurePosixPath(path).parts

    @staticmethod
    def _is_secret_path(path: str) -> bool:
        from neos.coding.domain.approvals import is_denied_secret_path

        return is_denied_secret_path(path)

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
        return PurePosixPath(path).match(normalized) or (
            normalized.startswith("**/")
            and PurePosixPath(path).match(normalized[3:])
        )


def _file_is_binary(item: Path) -> bool:
    try:
        with item.open("rb") as handle:
            sample = handle.read(8192)
    except OSError:
        return True
    return b"\0" in sample


def _read_file_range(
    item: Path, offset: int, limit: int, max_bytes: int
) -> bytes:
    end = offset + limit - 1
    chunks: list[bytes] = []
    remaining = max_bytes
    with item.open("rb") as handle:
        for index, line in enumerate(handle, start=1):
            if index < offset:
                continue
            if index > end:
                break
            if len(line) >= remaining:
                chunks.append(line[:remaining])
                break
            chunks.append(line)
            remaining -= len(line)
    return b"".join(chunks)


def _search_match(
    relative: str,
    line_number: int,
    column: int,
    line: str,
    lines: list[str],
    before: int,
    after: int,
    max_columns: int,
) -> SearchMatch:
    start = max(0, line_number - 1 - before)
    text = line if max_columns <= 0 else line[:max_columns]
    return SearchMatch(
        path=relative,
        line=line_number,
        column=column,
        text=text,
        before=tuple(lines[start : line_number - 1]),
        after=tuple(lines[line_number : line_number + after]),
    )
