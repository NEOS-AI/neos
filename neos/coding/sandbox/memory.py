from __future__ import annotations

import asyncio
import os
import re
import shutil
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


@dataclass(slots=True)
class _MemorySandboxRecord:
    sandbox: Sandbox
    workspace: Path
    lock: asyncio.Lock


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
    ) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._allowed_env_names = allowed_env_names
        self._process_runner = process_runner or BoundedProcessRunner()
        self._snapshot_store = LocalSnapshotStore(
            snapshot_root or (self._root / "_snapshots")
        )
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
            await asyncio.to_thread(item.write_bytes, content)
            return await self._provider._increment_revision(self._record)

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
        return await self._provider._process_runner.run(
            bounded_request,
            cwd=cwd,
            env=environment,
        )

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

    @staticmethod
    def _matches_path(path: str, pattern: str) -> bool:
        normalized = normalize_workspace_path(pattern).as_posix()
        if normalized.endswith("/**"):
            return path.startswith(normalized[:-3].rstrip("/") + "/")
        return PurePosixPath(path).match(normalized)
