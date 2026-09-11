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
    CommandResult,
    FileEntry,
    SearchMatch,
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
    WorkspaceChange,
    WorkspaceChangeKind,
)
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
)
from neos.coding.sandbox.streams import BoundedReplayStream


_READ_FILE_HELPER = """\
from pathlib import Path
import sys
p = Path('/workspace') / sys.argv[1]
if not p.is_file() or p.is_symlink(): raise SystemExit(2)
sys.stdout.buffer.write(p.read_bytes())
"""
_WRITE_FILE_HELPER = """\
import os, sys, tempfile
from pathlib import Path
rel, make_parents = sys.argv[1], sys.argv[2] == '1'
root = Path('/workspace')
parts = Path(rel).parts
p = root.joinpath(*parts)
cur = root
for part in parts[:-1]:
    cur = cur / part
    if cur.is_symlink():
        raise SystemExit(3)
    if cur.exists():
        if not cur.is_dir():
            raise SystemExit(2)
        continue
    if not make_parents:
        raise SystemExit(2)
    cur.mkdir(exist_ok=True)
    if cur.is_symlink() or not cur.is_dir():
        raise SystemExit(3 if cur.is_symlink() else 2)
if p.is_symlink():
    raise SystemExit(4)
fd, tmp = tempfile.mkstemp(prefix='.neos-write-', dir=str(p.parent))
try:
    with os.fdopen(fd, 'wb') as handle:
        handle.write(sys.stdin.buffer.read())
    os.replace(tmp, p)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
"""
_SEARCH_TEXT_HELPER = """\
import fnmatch, json, re, sys
from pathlib import Path
query, regex, limit, before, after, output_mode, *patterns = sys.argv[1:]
expression = re.compile(query if regex == '1' else re.escape(query))
before = max(0, min(int(before), 20))
after = max(0, min(int(after), 20))
if output_mode not in {'files', 'content', 'count'}:
    output_mode = 'content'
skip_dirs = {'.git','node_modules','__pycache__','.venv','venv','dist','build','.svn','.hg','.tox','.mypy_cache','.pytest_cache'}
def load_ignores():
    pats = []
    for name in ('.gitignore', '.ignore'):
        ig = Path('/workspace') / name
        if ig.is_file():
            for line in ig.read_text(errors='replace').splitlines():
                s = line.strip()
                if s and not s.startswith('#'): pats.append(s)
    return pats
def ignored(relative, pats):
    parts = Path(relative).parts
    if any(part in skip_dirs for part in parts): return True
    name = Path(relative).name
    if name == '.env' or name.startswith('.env.'): return True
    if '.ssh' in parts or name == 'id_rsa': return True
    if '.aws' in parts:
        try:
            if parts[parts.index('.aws') + 1] == 'credentials': return True
        except IndexError:
            pass
    hit = False
    for raw in pats:
        neg = raw.startswith('!')
        pat = raw[1:] if neg else raw
        pat = pat.lstrip('/').rstrip('/')
        if not pat: continue
        if fnmatch.fnmatch(relative, pat) or fnmatch.fnmatch(name, pat) or any(fnmatch.fnmatch(part, pat) for part in parts):
            hit = not neg
    return hit
ignores = load_ignores()
matches = []
for p in sorted(Path('/workspace').rglob('*')):
    if not p.is_file() or p.is_symlink(): continue
    relative = p.relative_to('/workspace').as_posix()
    if ignored(relative, ignores): continue
    if not any(fnmatch.fnmatch(relative, pattern) or
               (pattern.startswith('**/') and fnmatch.fnmatch(relative, pattern[3:]))
               for pattern in patterns): continue
    lines = p.read_text(errors='replace').splitlines()
    file_hits = 0
    for number, line in enumerate(lines, 1):
        match = expression.search(line)
        if not match: continue
        file_hits += 1
        if output_mode != 'content': continue
        start = max(0, number - 1 - before)
        matches.append({'path': relative, 'line': number,
                        'column': match.start() + 1, 'text': line,
                        'before': lines[start:number - 1],
                        'after': lines[number:number + after]})
        if len(matches) >= int(limit): break
    if output_mode == 'content':
        if len(matches) >= int(limit): break
        continue
    if file_hits == 0: continue
    if output_mode == 'files':
        matches.append({'path': relative, 'line': 0, 'column': 0, 'text': ''})
    else:
        matches.append({'path': relative, 'line': 0, 'column': 0, 'text': '',
                        'count': file_hits})
    if len(matches) >= int(limit): break
sys.stdout.write(json.dumps(matches))
"""
_GLOB_FILES_HELPER = """\
import fnmatch, json, sys
from pathlib import Path
pattern, limit = sys.argv[1], int(sys.argv[2])
if '..' in Path(pattern).parts:
    raise SystemExit(2)
limit = max(1, min(limit, 500))
skip_dirs = {'.git','node_modules','__pycache__','.venv','venv','dist','build','.svn','.hg','.tox','.mypy_cache','.pytest_cache'}
def load_ignores():
    pats = []
    for name in ('.gitignore', '.ignore'):
        ig = Path('/workspace') / name
        if ig.is_file():
            for line in ig.read_text(errors='replace').splitlines():
                s = line.strip()
                if s and not s.startswith('#'): pats.append(s)
    return pats
def ignored(relative, pats):
    parts = Path(relative).parts
    if any(part in skip_dirs for part in parts): return True
    name = Path(relative).name
    if name == '.env' or name.startswith('.env.'): return True
    if '.ssh' in parts or name == 'id_rsa': return True
    if '.aws' in parts:
        try:
            if parts[parts.index('.aws') + 1] == 'credentials': return True
        except IndexError:
            pass
    hit = False
    for raw in pats:
        neg = raw.startswith('!')
        pat = raw[1:] if neg else raw
        pat = pat.lstrip('/').rstrip('/')
        if not pat: continue
        if fnmatch.fnmatch(relative, pat) or fnmatch.fnmatch(name, pat) or any(fnmatch.fnmatch(part, pat) for part in parts):
            hit = not neg
    return hit
ignores = load_ignores()
found = []
for p in sorted(Path('/workspace').rglob('*')):
    if p.is_symlink(): continue
    relative = p.relative_to('/workspace').as_posix()
    if ignored(relative, ignores): continue
    if fnmatch.fnmatch(relative, pattern) or (
        pattern.startswith('**/') and fnmatch.fnmatch(relative, pattern[3:])
    ):
        found.append(relative)
        if len(found) >= limit: break
sys.stdout.write(json.dumps(found))
"""
_FILE_METADATA_HELPER = """\
import json, sys
from datetime import UTC, datetime
from pathlib import Path
root = Path('/workspace')
p = root / sys.argv[1]
def encode(item):
    value = item.lstat()
    kind = 'symlink' if item.is_symlink() else ('directory' if item.is_dir() else 'file')
    return {'path': item.relative_to(root).as_posix(), 'kind': kind,
            'size': value.st_size,
            'modified_at': datetime.fromtimestamp(value.st_mtime, UTC).isoformat()}
if sys.argv[2] == 'tree':
    result = [encode(item) for item in sorted(p.rglob('*'))]
else:
    if not p.exists() and not p.is_symlink():
        raise SystemExit(2)
    result = encode(p)
sys.stdout.write(json.dumps(result))
"""
_SNAPSHOT_HELPER = """\
import sys, tarfile
from pathlib import Path
root = Path('/workspace')
excluded = {'.env', '.git/credentials', '.neos/secrets'}
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for item in sorted(root.rglob('*')):
        relative = item.relative_to(root).as_posix()
        if relative in excluded or relative.startswith('.neos/secrets/'): continue
        if item.is_socket() or item.is_block_device() or item.is_char_device() or item.is_fifo(): continue
        archive.add(item, arcname=relative, recursive=False)
"""
_RESTORE_HELPER = """\
import sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|*') as archive:
    archive.extractall('/workspace', filter='data')
"""
_SCAN_HELPER = """\
import json
from pathlib import Path
root = Path('/workspace')
result = {}
for item in root.rglob('*'):
    if not item.is_file() or item.is_symlink(): continue
    relative = item.relative_to(root).as_posix()
    if relative.startswith('.git/') or relative.endswith(('.swp', '~')): continue
    value = item.stat()
    result[relative] = [value.st_size, value.st_mtime_ns]
print(json.dumps(result, sort_keys=True))
"""


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


class DockerSandboxSession:
    def __init__(
        self,
        provider: DockerSandboxProvider,
        record: _DockerRecord,
    ) -> None:
        self._provider = provider
        self._record = record

    @property
    def sandbox_id(self) -> str:
        return self._record.sandbox.sandbox_id

    async def workspace_revision(self) -> int:
        await self._provider._running_record(self.sandbox_id)
        return self._record.sandbox.workspace_revision

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

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        relative = normalize_workspace_path(path)
        result = await self._run_helper(
            _FILE_METADATA_HELPER,
            relative.as_posix(),
            "tree",
        )
        return tuple(self._file_entry(value) for value in self._load_json(result.stdout))

    async def stat(self, path: str) -> FileEntry:
        relative = normalize_workspace_path(path)
        try:
            result = await self._run_helper(
                _FILE_METADATA_HELPER,
                relative.as_posix(),
                "stat",
            )
        except SandboxUnavailable as error:
            if str(error) == "docker_command_failed:2":
                raise SandboxNotFound(relative.as_posix()) from error
            raise
        return self._file_entry(self._load_json(result.stdout))

    async def read_file(self, path: str) -> bytes:
        relative = normalize_workspace_path(path)
        result = await self._run_helper(_READ_FILE_HELPER, relative.as_posix())
        return result.stdout

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
        relative = ensure_mutable_workspace_path(path)
        limits = self._record.sandbox.limits
        if len(content) > min(limits.workspace_bytes, limits.max_stdin_bytes):
            raise SandboxPolicyViolation("workspace_write_limit_exceeded")
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            if (
                expected_revision is not None
                and self._record.sandbox.workspace_revision
                != expected_revision
            ):
                raise SandboxStateConflict("workspace_revision_conflict")
            try:
                await self._run_helper(
                    _WRITE_FILE_HELPER,
                    relative.as_posix(),
                    "1" if parents else "0",
                    input=content,
                )
            except SandboxUnavailable as error:
                code = str(error)
                if code == "docker_command_failed:2":
                    raise FileNotFoundError(relative.as_posix()) from error
                if code == "docker_command_failed:3":
                    raise SandboxPolicyViolation(
                        "workspace_symlink_parent"
                    ) from error
                if code == "docker_command_failed:4":
                    raise SandboxPolicyViolation(
                        "workspace_symlink_leaf"
                    ) from error
                raise
            existed = relative.as_posix() in self._record.known_paths
            self._record.known_paths.add(relative.as_posix())
            self._record.sandbox = replace(
                self._record.sandbox,
                workspace_revision=self._record.sandbox.workspace_revision + 1,
                updated_at=self._provider._clock(),
            )
            await self._record.watcher.record(
                WorkspaceChange(
                    path=relative.as_posix(),
                    kind=(
                        WorkspaceChangeKind.MODIFIED
                        if existed
                        else WorkspaceChangeKind.CREATED
                    ),
                ),
                revision=self._record.sandbox.workspace_revision,
            )
            return self._record.sandbox.workspace_revision

    async def watch_files(self, *, after_cursor: int = 0):
        await self._provider._running_record(self.sandbox_id)
        self._record.watching = True
        return self._record.watcher.open(after_cursor=after_cursor)

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
    ) -> tuple[SearchMatch, ...]:
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        if output_mode not in {"files", "content", "count"}:
            output_mode = "content"
        before = max(0, min(int(before), 20))
        after = max(0, min(int(after), 20))
        for path in paths:
            normalize_workspace_path(path)
        result = await self._run_helper(
            _SEARCH_TEXT_HELPER,
            query,
            "1" if regex else "0",
            str(limit),
            str(before),
            str(after),
            output_mode,
            *paths,
        )
        try:
            values = json.loads(result.stdout)
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
                for value in values
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            KeyError,
        ) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    async def glob_files(self, pattern: str, *, limit: int = 100) -> tuple[str, ...]:
        if not pattern or limit < 1:
            raise SandboxPolicyViolation("invalid_glob_request")
        normalize_workspace_path(
            pattern.replace("*", "x").replace("?", "x") or "x"
        )
        result = await self._run_helper(
            _GLOB_FILES_HELPER,
            pattern,
            str(min(int(limit), 500)),
        )
        try:
            values = json.loads(result.stdout)
            return tuple(values)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

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

    @staticmethod
    def _load_json(payload: bytes):
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    @staticmethod
    def _file_entry(value) -> FileEntry:
        try:
            return FileEntry(
                path=value["path"],
                kind=value["kind"],
                size=value["size"],
                modified_at=datetime.fromisoformat(value["modified_at"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    async def execute(self, request: CommandRequest) -> CommandResult:
        await self._provider._running_record(self.sandbox_id)
        disallowed = set(request.env) - self._provider._config.allowed_env_names
        if disallowed:
            raise SandboxPolicyViolation("environment_not_allowed")
        if len(request.stdin) > self._record.sandbox.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("command_stdin_limit_exceeded")
        relative_cwd = normalize_workspace_path(request.cwd)
        workdir = "/workspace"
        if relative_cwd != normalize_workspace_path("."):
            workdir = f"/workspace/{relative_cwd.as_posix()}"
        args = ["exec"]
        if request.stdin:
            args.append("-i")
        args.extend(("--workdir", workdir))
        for key, value in request.env.items():
            args.extend(("--env", f"{key}={value}"))
        args.append(self._record.container_name)
        args.extend(request.argv)
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            before = await self._scan_workspace()
            result = await self._provider._runner.run(
                *args,
                timeout_sec=min(
                    request.timeout_sec,
                    self._record.sandbox.limits.command_timeout_sec,
                ),
                allowed_exit_codes=tuple(range(256)),
                input=request.stdin,
            )
            after = await self._scan_workspace()
            await self._record_scan_changes(before, after)
        limit = min(
            request.max_output_bytes,
            self._record.sandbox.limits.max_output_bytes,
        )
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout[:limit],
            stderr=result.stderr[:limit],
            stdout_truncated=len(result.stdout) > limit,
            stderr_truncated=len(result.stderr) > limit,
        )

    async def _scan_workspace(self) -> dict[str, tuple[int, int]]:
        result = await self._run_helper(_SCAN_HELPER)
        values = self._load_json(result.stdout)
        try:
            return {path: tuple(value) for path, value in values.items()}
        except (AttributeError, TypeError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    async def _record_scan_changes(
        self,
        before: dict[str, tuple[int, int]],
        after: dict[str, tuple[int, int]],
    ) -> None:
        changes = []
        for path in sorted(before.keys() | after.keys()):
            if path not in before:
                kind = WorkspaceChangeKind.CREATED
            elif path not in after:
                kind = WorkspaceChangeKind.DELETED
            elif before[path] != after[path]:
                kind = WorkspaceChangeKind.MODIFIED
            else:
                continue
            changes.append(WorkspaceChange(path=path, kind=kind))
        if not changes:
            return
        self._record.sandbox = replace(
            self._record.sandbox,
            workspace_revision=self._record.sandbox.workspace_revision + 1,
            updated_at=self._provider._clock(),
        )
        self._record.known_paths = set(after)
        for change in changes:
            await self._record.watcher.record(
                change,
                revision=self._record.sandbox.workspace_revision,
            )
