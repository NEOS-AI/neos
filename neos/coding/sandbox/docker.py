from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neos.coding.sandbox.base import (
    CommandRequest,
    Sandbox,
    SandboxError,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
    SandboxUnavailable,
    Snapshot,
)
from neos.coding.sandbox.archive import (
    SNAPSHOT_SCHEMA_VERSION,
    LocalSnapshotStore,
    SnapshotManifest,
    extract_workspace_archive,
    sha256_file,
)
from neos.coding.sandbox.command import (
    DockerCommandRunner,
    DockerInteractiveProcess,
    _label_args,
    build_create_args,
)
from neos.coding.sandbox.events import (
    PtyClosed,
    PtyOutput,
    SandboxWatcherHub,
)
from neos.coding.sandbox.streams import BoundedReplayStream

from neos.coding.sandbox.helper_scripts import (
    _CHMOD_HELPER as _CHMOD_HELPER,
    _FILE_METADATA_HELPER as _FILE_METADATA_HELPER,
    _GIT_SAFE as _GIT_SAFE,
    _GLOB_FILES_HELPER as _GLOB_FILES_HELPER,
    _MKDIR_HELPER as _MKDIR_HELPER,
    _MV_HELPER as _MV_HELPER,
    _READ_FILE_HELPER as _READ_FILE_HELPER,
    _REFUSE_SYMLINK_PARENTS as _REFUSE_SYMLINK_PARENTS,
    _RESTORE_HELPER as _RESTORE_HELPER,
    _RM_HELPER as _RM_HELPER,
    _SCAN_HELPER as _SCAN_HELPER,
    _SEARCH_TEXT_HELPER as _SEARCH_TEXT_HELPER,
    _SNAPSHOT_HELPER as _SNAPSHOT_HELPER,
    _WRITE_FILE_HELPER as _WRITE_FILE_HELPER,
)
from neos.coding.sandbox.helper_session import (
    _RESERVED_GUEST_ENV as _RESERVED_GUEST_ENV,
    HelperScriptSandboxSession,
)


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_archive(path: Path, maximum: int) -> None:
    with tempfile.TemporaryDirectory(prefix="neos-snapshot-validate-") as root:
        extract_workspace_archive(
            path,
            Path(root),
            max_expanded_bytes=maximum,
        )


# 관리형 컨트롤 플레인이 이 provider가 만드는 리소스에 라벨을 얹는 공개 경로.
# ContextVar 이므로 같은 프로세스의 동시 create 가 서로 오염되지 않는다.
_MANAGED_LABELS: ContextVar[Mapping[str, str]] = ContextVar(
    "neos_docker_managed_labels", default={}
)


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    image: str
    create_timeout_sec: float = 30.0
    operation_timeout_sec: float = 30.0
    network_mode: str = "none"
    allow_unpinned_image: bool = False
    tmpfs_bytes: int = 64 * 1024 * 1024
    snapshot_root: Path | None = None
    max_snapshot_bytes: int = 16 * 1024 * 1024
    max_pty_sessions: int = 4
    pty_replay_events: int = 1024
    pty_replay_bytes: int = 1024 * 1024
    watcher_debounce_sec: float = 0.05
    watcher_replay_events: int = 1024
    allowed_env_names: frozenset[str] = frozenset(
        {"HOME", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR"}
    )



@dataclass(slots=True)
class _DockerRecord:
    sandbox: Sandbox
    container_name: str
    volume_name: str
    lock: asyncio.Lock
    ptys: dict[str, DockerPty]
    watcher: SandboxWatcherHub
    known_paths: set[str]
    watching: bool


class DockerPty:
    def __init__(
        self,
        *,
        pty_id: str,
        transport: Any,
        replay_events: int,
        replay_bytes: int,
    ) -> None:
        self.pty_id = pty_id
        self._transport = transport
        self._stream = BoundedReplayStream(
            max_events=replay_events,
            max_bytes=replay_bytes,
            size_of=lambda event: (
                len(event.data) if isinstance(event, PtyOutput) else 32
            ),
        )
        self._closed = asyncio.get_running_loop().create_future()
        self._requested_reason: str | None = None
        self._finish_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(
            self._read_output(),
            name=f"docker-sandbox-pty-{pty_id}",
        )

    @property
    def is_closed(self) -> bool:
        return self._closed.done()

    def subscribe(self, *, after_cursor: int):
        return self._stream.subscribe(after_cursor=after_cursor)

    async def replay(self, *, after_cursor: int):
        return await self._stream.replay(after_cursor=after_cursor)

    async def write(self, data: bytes) -> None:
        if self.is_closed:
            raise SandboxStateConflict("pty_closed")
        await self._transport.write(data)

    async def resize(self, *, rows: int, cols: int) -> None:
        if rows < 1 or cols < 1 or rows > 1000 or cols > 1000:
            raise SandboxPolicyViolation("pty_size_invalid")
        await self._transport.resize(rows=rows, cols=cols)

    async def terminate(self, reason: str) -> PtyClosed:
        if self.is_closed:
            return await self._closed
        self._requested_reason = reason
        await self._transport.terminate()
        await self._reader_task
        return await self._closed

    async def wait_closed(self) -> PtyClosed:
        return await self._closed

    async def _read_output(self) -> None:
        try:
            while True:
                data = await self._transport.read(4096)
                if not data:
                    break
                await self._stream.publish(PtyOutput(data=data))
        finally:
            exit_code = await self._transport.wait()
            reason = self._requested_reason or "process_exited"
            await self._finish(
                reason,
                None if self._requested_reason is not None else exit_code,
            )

    async def _finish(self, reason: str, exit_code: int | None) -> None:
        async with self._finish_lock:
            if self._closed.done():
                return
            closed = PtyClosed(reason=reason, exit_code=exit_code)
            await self._stream.publish(closed)
            await self._stream.close()
            self._closed.set_result(closed)


class DockerSandboxProvider:
    def __init__(
        self,
        *,
        runner: DockerCommandRunner,
        config: DockerSandboxConfig,
        clock=None,
        interactive_factory=None,
    ) -> None:
        self._runner = runner
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._interactive_factory = (
            interactive_factory or DockerInteractiveProcess.start
        )
        self._temporary_snapshot_root = None
        snapshot_root = config.snapshot_root
        if snapshot_root is None:
            self._temporary_snapshot_root = tempfile.TemporaryDirectory(
                prefix="neos-docker-snapshots-"
            )
            snapshot_root = Path(self._temporary_snapshot_root.name)
        self._snapshot_store = LocalSnapshotStore(snapshot_root)
        self._records: dict[str, _DockerRecord] = {}
        self._lock = asyncio.Lock()

    @contextmanager
    def resource_labels(self, labels: Mapping[str, str]):
        """블록 안에서 만들어지는 컨테이너·볼륨에 `labels` 를 붙인다."""
        token = _MANAGED_LABELS.set(dict(labels))
        try:
            yield
        finally:
            _MANAGED_LABELS.reset(token)

    @property
    def command_runner(self) -> DockerCommandRunner:
        """관리형 어댑터가 자기 리소스를 다룰 docker 클라이언트.

        읽기 전용이다 -- 이 러너를 **교체**하는 것이 CA5-a 가 없애려는 결함이었다.
        """
        return self._runner

    @property
    def network_mode(self) -> str:
        return self._config.network_mode

    @property
    def image_identity(self) -> str:
        return self._config.image

    @property
    def create_timeout_sec(self) -> float:
        return self._config.create_timeout_sec

    @property
    def operation_timeout_sec(self) -> float:
        return self._config.operation_timeout_sec

    async def create(
        self,
        *,
        owner_id: str,
        limits: SandboxLimits,
    ) -> Sandbox:
        sandbox_id = f"sb_{uuid.uuid4().hex}"
        container_name = f"neos-{sandbox_id}"
        volume_name = f"neos-sandbox-{sandbox_id}"
        now = self._clock()
        sandbox = Sandbox.creating(
            sandbox_id,
            owner_id,
            limits,
            now,
            provider="docker",
            image_digest=self._config.image,
        )
        volume_created = False
        container_created = False
        managed_labels = _MANAGED_LABELS.get()
        try:
            await self._runner.run(
                "volume",
                "create",
                "--label",
                "com.neos.coding.sandbox=true",
                "--label",
                f"com.neos.coding.sandbox-id={sandbox_id}",
                *_label_args(managed_labels),
                volume_name,
                timeout_sec=self._config.create_timeout_sec,
            )
            volume_created = True
            create_args = list(
                build_create_args(
                    sandbox_id=sandbox_id,
                    image=self._config.image,
                    limits=limits,
                    network_mode=self._config.network_mode,
                    allow_unpinned_image=self._config.allow_unpinned_image,
                    tmpfs_bytes=self._config.tmpfs_bytes,
                    extra_labels={
                        "com.neos.coding.owner-id": owner_id,
                        "com.neos.coding.created-at": now.isoformat(),
                        "com.neos.coding.workspace-revision": "0",
                        **managed_labels,
                    },
                )
            )
            await self._runner.run(
                *create_args,
                timeout_sec=self._config.create_timeout_sec,
            )
            container_created = True
            await self._runner.run(
                "start",
                container_name,
                timeout_sec=self._config.create_timeout_sec,
            )
            await self._probe(container_name)
        except BaseException:
            if container_created:
                await self._cleanup_command("rm", "--force", container_name)
            if volume_created:
                await self._cleanup_command("volume", "rm", volume_name)
            raise

        running = sandbox.transition(SandboxState.RUNNING, self._clock())
        async with self._lock:
            self._records[sandbox_id] = _DockerRecord(
                sandbox=running,
                container_name=container_name,
                volume_name=volume_name,
                lock=asyncio.Lock(),
                ptys={},
                watcher=SandboxWatcherHub(
                    debounce_sec=self._config.watcher_debounce_sec,
                    replay_events=self._config.watcher_replay_events,
                ),
                known_paths=set(),
                watching=False,
            )
        return running

    async def get(self, sandbox_id: str) -> Sandbox:
        return (await self._record(sandbox_id)).sandbox

    async def reconcile(self) -> tuple[Sandbox, ...]:
        listed = await self._runner.run(
            "ps",
            "--all",
            "--filter",
            "label=com.neos.coding.sandbox=true",
            "--format",
            "{{.ID}}",
            timeout_sec=self._config.operation_timeout_sec,
        )
        container_ids = tuple(
            value for value in listed.stdout.decode().splitlines() if value
        )
        if not container_ids:
            async with self._lock:
                return tuple(
                    self._records[key].sandbox for key in sorted(self._records)
                )
        inspected = await self._runner.run(
            "inspect",
            *container_ids,
            timeout_sec=self._config.operation_timeout_sec,
        )
        try:
            values = json.loads(inspected.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SandboxUnavailable("docker_inspect_output_invalid") from error
        recovered: list[Sandbox] = []
        async with self._lock:
            for value in values:
                record = self._record_from_inspect(value)
                if record is None:
                    continue
                existing = self._records.get(record.sandbox.sandbox_id)
                if existing is None:
                    self._records[record.sandbox.sandbox_id] = record
                    existing = record
                recovered.append(existing.sandbox)
        return tuple(sorted(recovered, key=lambda item: item.sandbox_id))

    def _record_from_inspect(self, value) -> _DockerRecord | None:
        try:
            labels = value["Config"]["Labels"] or {}
            if labels.get("com.neos.coding.sandbox") != "true":
                return None
            sandbox_id = labels["com.neos.coding.sandbox-id"]
            owner_id = labels["com.neos.coding.owner-id"]
            created_at = datetime.fromisoformat(
                labels["com.neos.coding.created-at"]
            )
            revision = int(labels["com.neos.coding.workspace-revision"])
            if (
                not sandbox_id.startswith("sb_")
                or value["Name"] != f"/neos-{sandbox_id}"
                or not owner_id
                or revision < 0
            ):
                return None
            state = (
                SandboxState.RUNNING
                if value["State"]["Running"]
                else SandboxState.SUSPENDED
            )
        except (KeyError, TypeError, ValueError):
            return None
        sandbox = Sandbox(
            sandbox_id=sandbox_id,
            owner_id=owner_id,
            state=state,
            limits=SandboxLimits.safe_defaults(),
            created_at=created_at,
            updated_at=self._clock(),
            workspace_revision=revision,
            provider="docker",
            image_digest=self._config.image,
        )
        return _DockerRecord(
            sandbox=sandbox,
            container_name=f"neos-{sandbox_id}",
            volume_name=f"neos-sandbox-{sandbox_id}",
            lock=asyncio.Lock(),
            ptys={},
            watcher=SandboxWatcherHub(
                debounce_sec=self._config.watcher_debounce_sec,
                replay_events=self._config.watcher_replay_events,
            ),
            known_paths=set(),
            watching=False,
        )

    async def suspend(self, sandbox_id: str) -> Sandbox:
        record = await self._running_record(sandbox_id)
        async with record.lock:
            await self._terminate_ptys(record, "sandbox_suspended")
            await self._runner.run(
                "stop",
                record.container_name,
                timeout_sec=self._config.operation_timeout_sec,
            )
            record.sandbox = record.sandbox.transition(
                SandboxState.SUSPENDED,
                self._clock(),
            )
            return record.sandbox

    async def resume(self, sandbox_id: str) -> Sandbox:
        record = await self._record(sandbox_id)
        async with record.lock:
            if record.sandbox.state is not SandboxState.SUSPENDED:
                raise SandboxStateConflict(
                    f"sandbox_{record.sandbox.state.value}"
                )
            await self._runner.run(
                "start",
                record.container_name,
                timeout_sec=self._config.operation_timeout_sec,
            )
            await self._probe(record.container_name)
            record.sandbox = record.sandbox.transition(
                SandboxState.RUNNING,
                self._clock(),
            )
            return record.sandbox

    async def destroy(self, sandbox_id: str) -> None:
        async with self._lock:
            record = self._records.pop(sandbox_id, None)
        if record is None:
            return
        async with record.lock:
            await self._terminate_ptys(record, "sandbox_destroyed")
            await record.watcher.close()
            await self._cleanup_command(
                "rm",
                "--force",
                record.container_name,
            )
            await self._cleanup_command(
                "volume",
                "rm",
                record.volume_name,
            )
            record.sandbox = record.sandbox.transition(
                SandboxState.DESTROYED,
                self._clock(),
            )

    async def snapshot(self, sandbox_id: str) -> Snapshot:
        record = await self._record(sandbox_id)
        if record.sandbox.state not in {
            SandboxState.RUNNING,
            SandboxState.SUSPENDED,
        }:
            raise SandboxStateConflict(f"sandbox_{record.sandbox.state.value}")
        async with record.lock:
            result = await self._runner.run(
                "exec",
                record.container_name,
                "python",
                "-c",
                _SNAPSHOT_HELPER,
                timeout_sec=self._config.operation_timeout_sec,
            )
            if result.stdout_truncated:
                raise SandboxUnavailable("snapshot_archive_truncated")
            if len(result.stdout) > self._config.max_snapshot_bytes:
                raise SandboxPolicyViolation("snapshot_archive_size_exceeded")
            snapshot_id = f"ss_{uuid.uuid4().hex}"
            archive_path = self._snapshot_store.archive_path(snapshot_id)
            await asyncio.to_thread(_write_atomic, archive_path, result.stdout)
            try:
                await asyncio.to_thread(
                    _validate_archive,
                    archive_path,
                    self._config.max_snapshot_bytes,
                )
                checksum = await asyncio.to_thread(sha256_file, archive_path)
                created_at = self._clock()
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
            except BaseException:
                archive_path.unlink(missing_ok=True)
                raise
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
        if await asyncio.to_thread(sha256_file, archive_path) != manifest.content_checksum:
            raise SandboxPolicyViolation("snapshot_checksum_mismatch")
        archive = await asyncio.to_thread(archive_path.read_bytes)
        if len(archive) > self._config.max_snapshot_bytes:
            raise SandboxPolicyViolation("snapshot_archive_size_exceeded")
        restored: Sandbox | None = None
        complete = False
        try:
            restored = await self.create(
                owner_id=owner_id,
                limits=SandboxLimits.safe_defaults(),
            )
            record = await self._record(restored.sandbox_id)
            async with record.lock:
                await self._runner.run(
                    "exec",
                    "-i",
                    record.container_name,
                    "python",
                    "-c",
                    _RESTORE_HELPER,
                    timeout_sec=self._config.operation_timeout_sec,
                    input=archive,
                )
                record.sandbox = replace(
                    record.sandbox,
                    workspace_revision=manifest.workspace_revision,
                    updated_at=self._clock(),
                )
                complete = True
                return record.sandbox
        finally:
            if restored is not None and not complete:
                await self.destroy(restored.sandbox_id)

    async def open_session(self, sandbox_id: str) -> DockerSandboxSession:
        record = await self._running_record(sandbox_id)
        return DockerSandboxSession(self, record)

    async def close(self) -> None:
        async with self._lock:
            sandbox_ids = tuple(self._records)
        for sandbox_id in sandbox_ids:
            await self.destroy(sandbox_id)
        if self._temporary_snapshot_root is not None:
            self._temporary_snapshot_root.cleanup()

    async def _record(self, sandbox_id: str) -> _DockerRecord:
        async with self._lock:
            record = self._records.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        return record

    async def _running_record(self, sandbox_id: str) -> _DockerRecord:
        record = await self._record(sandbox_id)
        if record.sandbox.state is not SandboxState.RUNNING:
            raise SandboxStateConflict(
                f"sandbox_{record.sandbox.state.value}"
            )
        return record

    async def _probe(self, container_name: str) -> None:
        await self._runner.run(
            "exec",
            container_name,
            "test",
            "-d",
            "/workspace",
            timeout_sec=self._config.create_timeout_sec,
        )

    async def _cleanup_command(self, *args: str) -> None:
        try:
            await self._runner.run(
                *args,
                timeout_sec=self._config.operation_timeout_sec,
            )
        except SandboxError:
            pass

    @staticmethod
    async def _terminate_ptys(record: _DockerRecord, reason: str) -> None:
        terminals = tuple(record.ptys.values())
        record.ptys.clear()
        for terminal in terminals:
            await terminal.terminate(reason)


class DockerSandboxSession(HelperScriptSandboxSession):
    """Helper-script session whose transport is `docker exec`."""

    _INVALID_OUTPUT = "docker_helper_output_invalid"

    def __init__(
        self,
        provider: DockerSandboxProvider,
        record: _DockerRecord,
    ) -> None:
        super().__init__(record)
        self._provider = provider

    async def _ensure_running(self) -> None:
        await self._provider._running_record(self.sandbox_id)

    @property
    def _allowed_env_names(self) -> frozenset[str]:
        return self._provider._config.allowed_env_names

    def _now(self) -> datetime:
        return self._provider._clock()

    async def _run_helper(
        self,
        helper: str,
        *args: str,
        input: bytes = b"",
    ):
        await self._provider._running_record(self.sandbox_id)
        return await self._provider._runner.run(
            "exec",
            "-i",
            self._record.container_name,
            "python",
            "-c",
            helper,
            *args,
            timeout_sec=self._provider._config.operation_timeout_sec,
            input=input,
        )

    async def _run_command(
        self,
        request: CommandRequest,
        *,
        workdir: str,
        env: Mapping[str, str],
        timeout_sec: float,
    ):
        args = ["exec"]
        if request.stdin:
            args.append("-i")
        args.extend(("--workdir", workdir))
        for key, value in env.items():
            args.extend(("--env", f"{key}={value}"))
        args.append(self._record.container_name)
        args.extend(request.argv)
        return await self._provider._runner.run(
            *args,
            timeout_sec=timeout_sec,
            allowed_exit_codes=tuple(range(256)),
            input=request.stdin,
        )

    async def create_pty(self, *, argv: tuple[str, ...]) -> DockerPty:
        CommandRequest(argv=argv)
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            active = sum(
                not terminal.is_closed for terminal in self._record.ptys.values()
            )
            if active >= self._provider._config.max_pty_sessions:
                raise SandboxPolicyViolation("pty_session_limit_exceeded")
            transport = await self._provider._interactive_factory(
                "exec",
                "-i",
                "-t",
                self._record.container_name,
                *argv,
            )
            pty_id = f"pty_{uuid.uuid4().hex}"
            terminal = DockerPty(
                pty_id=pty_id,
                transport=transport,
                replay_events=self._provider._config.pty_replay_events,
                replay_bytes=self._provider._config.pty_replay_bytes,
            )
            self._record.ptys[pty_id] = terminal
            return terminal

    async def write_pty(self, pty_id: str, data: bytes) -> None:
        if len(data) > self._record.sandbox.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("pty_input_limit_exceeded")
        await (await self._pty(pty_id)).write(data)

    async def resize_pty(self, pty_id: str, *, rows: int, cols: int) -> None:
        await (await self._pty(pty_id)).resize(rows=rows, cols=cols)

    async def kill_pty(self, pty_id: str) -> None:
        terminal = await self._pty(pty_id)
        await terminal.terminate("pty_killed")
        self._record.ptys.pop(pty_id, None)

    async def _pty(self, pty_id: str) -> DockerPty:
        await self._provider._running_record(self.sandbox_id)
        terminal = self._record.ptys.get(pty_id)
        if terminal is None:
            raise SandboxNotFound(pty_id)
        return terminal

