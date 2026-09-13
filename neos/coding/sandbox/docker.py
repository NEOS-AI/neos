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
from neos.coding.sandbox.ignore import IGNORE_RUNTIME
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
)
from neos.coding.sandbox.streams import BoundedReplayStream

_GIT_SAFE = ("git", "--no-pager", "-c", "core.pager=cat")


_READ_FILE_HELPER = """\
from pathlib import Path
import sys
rel, offset_s, limit_s, max_s = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = Path('/workspace') / rel
if not p.is_file() or p.is_symlink(): raise SystemExit(2)
offset = int(offset_s)
max_bytes = int(max_s)
if limit_s == '':
    if p.stat().st_size > max_bytes:
        raise SystemExit(3)
    sys.stdout.buffer.write(p.read_bytes())
else:
    limit = int(limit_s)
    start = max(1, offset)
    end = start + limit - 1
    remaining = max_bytes
    with p.open('rb') as handle:
        for index, line in enumerate(handle, 1):
            if index < start: continue
            if index > end: break
            if len(line) >= remaining:
                sys.stdout.buffer.write(line[:remaining])
                break
            sys.stdout.buffer.write(line)
            remaining -= len(line)
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
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, p)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
"""
_MKDIR_HELPER = """\
from pathlib import Path
import sys
rel, parents = sys.argv[1], sys.argv[2] == '1'
root = Path('/workspace')
parts = Path(rel).parts
p = root.joinpath(*parts)
cur = root
for part in parts[:-1]:
    cur = cur / part
    if cur.is_symlink():
        raise SystemExit(3)
    if not cur.exists():
        if not parents:
            raise SystemExit(2)
        cur.mkdir(exist_ok=True)
    elif not cur.is_dir():
        raise SystemExit(2)
if p.exists() and not parents:
    raise SystemExit(5)
if parents:
    p.mkdir(parents=True, exist_ok=True)
else:
    p.mkdir()
"""
_REFUSE_SYMLINK_PARENTS = """\
def _join_refusing_symlink_parents(root, rel):
    parts = Path(rel).parts
    cur = root
    for part in parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise SystemExit(3)
    return root.joinpath(*parts)
"""
_RM_HELPER = (
    _REFUSE_SYMLINK_PARENTS
    + """\
import shutil
from pathlib import Path
import sys
rel, recursive = sys.argv[1], sys.argv[2] == '1'
root = Path('/workspace')
p = _join_refusing_symlink_parents(root, rel)
if p.is_symlink():
    p.unlink()
elif p.is_dir():
    if any(p.iterdir()) and not recursive:
        raise SystemExit(6)
    shutil.rmtree(p) if recursive else p.rmdir()
elif p.exists():
    p.unlink()
else:
    raise SystemExit(2)
"""
)
_MV_HELPER = (
    _REFUSE_SYMLINK_PARENTS
    + """\
import shutil
from pathlib import Path
import sys
src, dest, overwrite = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
root = Path('/workspace')
s = _join_refusing_symlink_parents(root, src)
d = _join_refusing_symlink_parents(root, dest)
if not s.exists() and not s.is_symlink():
    raise SystemExit(2)
if not d.parent.exists():
    raise SystemExit(2)
if (d.exists() or d.is_symlink()) and not overwrite:
    raise SystemExit(5)
if d.exists() or d.is_symlink():
    if d.is_dir() and not d.is_symlink():
        shutil.rmtree(d)
    else:
        d.unlink()
s.rename(d)
"""
)
_CHMOD_HELPER = (
    _REFUSE_SYMLINK_PARENTS
    + """\
import os
from pathlib import Path
import sys
rel, mode = sys.argv[1], int(sys.argv[2])
root = Path('/workspace')
p = _join_refusing_symlink_parents(root, rel)
if not p.exists() and not p.is_symlink():
    raise SystemExit(2)
try:
    os.chmod(p, mode, follow_symlinks=False)
except NotImplementedError:
    os.chmod(p, mode)
"""
)
_SEARCH_TEXT_HELPER = (
    IGNORE_RUNTIME
    + """
import json, re, sys
from pathlib import Path
query, regex, limit, before, after, output_mode, ignore_case, multiline, max_columns, search_path, exclude_json, *patterns = sys.argv[1:]
flags = 0
if ignore_case == '1':
    flags |= re.IGNORECASE
if multiline == '1':
    flags |= re.DOTALL
expression = re.compile(query if regex == '1' else re.escape(query), flags)
before = max(0, min(int(before), 20))
after = max(0, min(int(after), 20))
max_columns = int(max_columns)
try:
    excludes = json.loads(exclude_json)
    if not isinstance(excludes, list):
        excludes = []
except (TypeError, ValueError):
    excludes = []
excludes = [str(item) for item in excludes]
if output_mode not in {'files', 'content', 'count'}:
    output_mode = 'content'
root = Path('/workspace')
start = root / search_path if search_path else root
rules = load_ignore_rules('/workspace')
matches = []

def is_binary(item):
    try:
        with item.open('rb') as handle:
            return b'\\x00' in handle.read(8192)
    except OSError:
        return True

def matches_glob(relative, pattern):
    if pattern.endswith('/**'):
        return relative.startswith(pattern[:-3].rstrip('/') + '/')
    try:
        if Path(relative).match(pattern):
            return True
    except (ValueError, OSError):
        return False
    return pattern.startswith('**/') and Path(relative).match(pattern[3:])

def clip(line):
    if max_columns <= 0:
        return line
    data = line.encode('utf-8')
    if len(data) <= max_columns:
        return line
    return data[:max_columns].decode('utf-8', errors='ignore')

def emit_content(relative, number, column, line, lines):
    ctx = max(0, number - 1 - before)
    matches.append({'path': relative, 'line': number, 'column': column,
                    'text': clip(line),
                    'before': [clip(item) for item in lines[ctx:number - 1]],
                    'after': [clip(item) for item in lines[number:number + after]]})

def consider_file(item, relative):
    if not any(matches_glob(relative, pattern) for pattern in patterns):
        return False
    if excludes and any(matches_glob(relative, pattern) for pattern in excludes):
        return False
    if is_binary(item):
        return False
    max_file_bytes = 1024 * 1024
    try:
        if item.stat().st_size > max_file_bytes:
            return False
        with item.open('rb') as handle:
            data = handle.read(max_file_bytes + 1)
    except OSError:
        return False
    if len(data) > max_file_bytes or b'\\x00' in data[:8192]:
        return False
    text = data.decode('utf-8', errors='replace')
    lines = text.splitlines()
    if multiline == '1':
        file_hits = 0
        for match in expression.finditer(text):
            file_hits += 1
            if output_mode != 'content':
                continue
            number = text.count('\\n', 0, match.start()) + 1
            line_start = text.rfind('\\n', 0, match.start()) + 1
            line_end = text.find('\\n', match.start())
            if line_end < 0:
                line_end = len(text)
            line = text[line_start:line_end].rstrip('\\r')
            emit_content(relative, number, match.start() - line_start + 1, line, lines)
            if len(matches) >= int(limit):
                return True
        if output_mode == 'content' or file_hits == 0:
            return False
    else:
        file_hits = 0
        for number, line in enumerate(lines, 1):
            match = expression.search(line)
            if not match:
                continue
            file_hits += 1
            if output_mode != 'content':
                continue
            emit_content(relative, number, match.start() + 1, line, lines)
            if len(matches) >= int(limit):
                return True
        if output_mode == 'content' or file_hits == 0:
            return False
    if output_mode == 'files':
        matches.append({'path': relative, 'line': 0, 'column': 0, 'text': ''})
    else:
        matches.append({'path': relative, 'line': 0, 'column': 0, 'text': '',
                        'count': file_hits})
    return len(matches) >= int(limit)

done = False
if start.is_symlink():
    pass
elif start.is_file():
    relative = start.relative_to(root).as_posix()
    if not should_skip(relative, rules, is_dir=False):
        consider_file(start, relative)
elif start.is_dir():
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        current = Path(dirpath)
        dirnames.sort(); filenames.sort()
        kept = []
        for name in dirnames:
            item = current / name
            if item.is_symlink():
                continue
            relative = item.relative_to(root).as_posix()
            if should_skip(relative, rules, is_dir=True):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            item = current / name
            if item.is_symlink() or not item.is_file():
                continue
            relative = item.relative_to(root).as_posix()
            if should_skip(relative, rules, is_dir=False):
                continue
            if consider_file(item, relative):
                done = True
                break
        if done:
            break
sys.stdout.write(json.dumps(matches))
"""
)
_GLOB_FILES_HELPER = (
    IGNORE_RUNTIME
    + """
import fnmatch, json, sys
from pathlib import Path
pattern, limit = sys.argv[1], int(sys.argv[2])
start = sys.argv[3] if len(sys.argv) > 3 else ''
if '..' in Path(pattern).parts or (start and '..' in Path(start).parts):
    raise SystemExit(2)
limit = max(1, min(limit, 500))
root = Path('/workspace')
base = (root / start) if start else root
if not base.exists():
    sys.stdout.write(json.dumps([]))
    raise SystemExit(0)
rules = load_ignore_rules('/workspace')
found = []
def matches(relative, from_start):
    for candidate in (relative, from_start):
        if fnmatch.fnmatch(candidate, pattern) or (
            pattern.startswith('**/') and fnmatch.fnmatch(candidate, pattern[3:])
        ):
            return True
    return False
for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
    current = Path(dirpath)
    dirnames.sort(); filenames.sort()
    kept = []
    for name in dirnames:
        item = current / name
        if item.is_symlink():
            continue
        relative = item.relative_to(root).as_posix()
        if should_skip(relative, rules, is_dir=True):
            continue
        kept.append(name)
    dirnames[:] = kept
    for name in filenames:
        item = current / name
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        if should_skip(relative, rules, is_dir=False):
            continue
        from_start = item.relative_to(base).as_posix()
        if matches(relative, from_start):
            found.append((item.stat().st_mtime, relative))
found.sort(key=lambda pair: (-pair[0], pair[1]))
sys.stdout.write(json.dumps([path for _mtime, path in found[:limit]]))
"""
)
_FILE_METADATA_HELPER = (
    IGNORE_RUNTIME
    + """
import json, os, sys
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
    rules = load_ignore_rules('/workspace')
    result = []
    if p.is_dir() and not p.is_symlink():
        for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
            current = Path(dirpath)
            kept = []
            for name in dirnames:
                item = current / name
                relative = item.relative_to(root).as_posix()
                if should_skip(relative, rules, is_dir=True):
                    continue
                kept.append(name)
                result.append(encode(item))
            dirnames[:] = kept
            for name in filenames:
                item = current / name
                relative = item.relative_to(root).as_posix()
                if should_skip(relative, rules, is_dir=False):
                    continue
                result.append(encode(item))
    result.sort(key=lambda row: row['path'])
else:
    if not p.exists() and not p.is_symlink():
        raise SystemExit(2)
    result = encode(p)
sys.stdout.write(json.dumps(result))
"""
)
_SNAPSHOT_HELPER = """\
import os, sys, tarfile
from pathlib import Path

def is_secret(rel):
    if rel in {'.env', '.git/credentials', '.neos/secrets'} or rel.startswith('.neos/secrets/'):
        return True
    parts = tuple(p for p in rel.replace('\\\\', '/').split('/') if p not in {'', '.'})
    if not parts:
        return False
    folded = tuple(p.casefold() for p in parts)
    name = folded[-1]
    if name == '.env' or name.startswith('.env.'):
        return True
    if '.git' in folded or '.ssh' in folded:
        return True
    if name == 'id_rsa':
        return True
    return any(part == '.aws' and folded[i + 1] == 'credentials' for i, part in enumerate(folded[:-1]))

root = Path('/workspace')
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept = []
        for name in sorted(dirnames):
            item = current / name
            relative = item.relative_to(root).as_posix()
            if item.is_symlink() or is_secret(relative):
                continue
            kept.append(name)
            archive.add(item, arcname=relative, recursive=False)
        dirnames[:] = kept
        for name in sorted(filenames):
            item = current / name
            relative = item.relative_to(root).as_posix()
            if item.is_symlink() or is_secret(relative):
                continue
            if item.is_socket() or item.is_block_device() or item.is_char_device() or item.is_fifo():
                continue
            archive.add(item, arcname=relative, recursive=False)
"""
_RESTORE_HELPER = """\
import sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|*') as archive:
    archive.extractall('/workspace', filter='data')
"""
_SCAN_HELPER = """\
import json, os
from pathlib import Path

def is_secret(rel):
    parts = tuple(p for p in rel.replace('\\\\', '/').split('/') if p not in {'', '.'})
    if not parts:
        return False
    folded = tuple(p.casefold() for p in parts)
    name = folded[-1]
    if name == '.env' or name.startswith('.env.'):
        return True
    if '.git' in folded or '.ssh' in folded:
        return True
    if name == 'id_rsa':
        return True
    return any(part == '.aws' and folded[i + 1] == 'credentials' for i, part in enumerate(folded[:-1]))

root = Path('/workspace')
result = {}
for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
    current = Path(dirpath)
    kept = []
    for name in dirnames:
        item = current / name
        if item.is_symlink():
            continue
        relative = item.relative_to(root).as_posix()
        if is_secret(relative) or relative.startswith('.git/') or relative.endswith(('.swp', '~')):
            continue
        kept.append(name)
    dirnames[:] = kept
    for name in filenames:
        item = current / name
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        if is_secret(relative) or relative.startswith('.git/') or relative.endswith(('.swp', '~')):
            continue
        value = item.lstat()
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


_RESERVED_GUEST_ENV = frozenset({"PATH", "HOME", "TMPDIR"})


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
        from neos.coding.sandbox.ignore import should_skip_walk

        relative = normalize_workspace_path(path)
        result = await self._run_helper(
            _FILE_METADATA_HELPER,
            relative.as_posix(),
            "tree",
        )
        return tuple(
            entry
            for entry in (
                self._file_entry(value) for value in self._load_json(result.stdout)
            )
            if not should_skip_walk(entry.path)
        )

    async def stat(self, path: str) -> FileEntry:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = normalize_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
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

    async def read_file(
        self,
        path: str,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> bytes:
        relative = normalize_workspace_path(path)
        if offset < 1 or (limit is not None and limit < 1):
            raise SandboxPolicyViolation("invalid_read_request")
        max_bytes = self._record.sandbox.limits.max_output_bytes
        try:
            result = await self._run_helper(
                _READ_FILE_HELPER,
                relative.as_posix(),
                str(offset),
                "" if limit is None else str(limit),
                str(max_bytes),
            )
        except SandboxUnavailable as error:
            if str(error) == "docker_command_failed:3":
                raise SandboxPolicyViolation("file_read_limit_exceeded") from error
            raise
        return result.stdout[:max_bytes]

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

    async def _record_mutation(
        self, path: str, *, kind: WorkspaceChangeKind
    ) -> int:
        self._record.known_paths.add(path)
        self._record.sandbox = replace(
            self._record.sandbox,
            workspace_revision=self._record.sandbox.workspace_revision + 1,
            updated_at=self._provider._clock(),
        )
        await self._record.watcher.record(
            WorkspaceChange(path=path, kind=kind),
            revision=self._record.sandbox.workspace_revision,
        )
        return self._record.sandbox.workspace_revision

    def _raise_helper_error(self, error: SandboxUnavailable) -> None:
        code = str(error)
        if code == "docker_command_failed:2":
            raise SandboxPolicyViolation("workspace_path_not_resolvable") from error
        if code == "docker_command_failed:3":
            raise SandboxPolicyViolation("workspace_symlink_parent") from error
        if code == "docker_command_failed:5":
            raise SandboxPolicyViolation("workspace_path_exists") from error
        if code == "docker_command_failed:6":
            raise SandboxPolicyViolation("workspace_directory_not_empty") from error
        raise error

    async def mkdir(self, path: str, *, parents: bool = False) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            try:
                await self._run_helper(
                    _MKDIR_HELPER, relative.as_posix(), "1" if parents else "0"
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                relative.as_posix(), kind=WorkspaceChangeKind.CREATED
            )

    async def rm(self, path: str, *, recursive: bool = False) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            try:
                await self._run_helper(
                    _RM_HELPER, relative.as_posix(), "1" if recursive else "0"
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                relative.as_posix(), kind=WorkspaceChangeKind.DELETED
            )

    async def mv(
        self, src: str, dest: str, *, overwrite: bool = False
    ) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        src_rel = ensure_mutable_workspace_path(src)
        dest_rel = ensure_mutable_workspace_path(dest)
        if is_denied_secret_path(src_rel.as_posix()) or is_denied_secret_path(
            dest_rel.as_posix()
        ):
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            try:
                await self._run_helper(
                    _MV_HELPER,
                    src_rel.as_posix(),
                    dest_rel.as_posix(),
                    "1" if overwrite else "0",
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                dest_rel.as_posix(), kind=WorkspaceChangeKind.MODIFIED
            )

    async def chmod(self, path: str, mode: int) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()) and mode & 0o002:
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            try:
                await self._run_helper(
                    _CHMOD_HELPER, relative.as_posix(), str(int(mode))
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                relative.as_posix(), kind=WorkspaceChangeKind.MODIFIED
            )

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
        ignore_case: bool = False,
        multiline: bool = False,
        context: int = 0,
        path: str | None = None,
        max_columns: int = 500,
        exclude: tuple[str, ...] = (),
    ) -> tuple[SearchMatch, ...]:
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        if output_mode not in {"files", "content", "count"}:
            output_mode = "content"
        if context > 0:
            before = after = context
        before = max(0, min(int(before), 20))
        after = max(0, min(int(after), 20))
        for candidate in paths:
            normalize_workspace_path(candidate)
        for candidate in exclude:
            normalize_workspace_path(candidate)
        search_path = ""
        if path is not None:
            normalized = normalize_workspace_path(path)
            search_path = "" if normalized.as_posix() == "." else normalized.as_posix()
        result = await self._run_helper(
            _SEARCH_TEXT_HELPER,
            query,
            "1" if regex else "0",
            str(limit),
            str(before),
            str(after),
            output_mode,
            "1" if ignore_case else "0",
            "1" if multiline else "0",
            str(max_columns),
            search_path,
            json.dumps(list(exclude)),
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

    async def glob_files(
        self,
        pattern: str,
        *,
        limit: int = 100,
        path: str | None = None,
    ) -> tuple[str, ...]:
        if not pattern or limit < 1:
            raise SandboxPolicyViolation("invalid_glob_request")
        normalize_workspace_path(
            pattern.replace("*", "x").replace("?", "x") or "x"
        )
        args = [pattern, str(min(int(limit), 500))]
        if path:
            args.append(normalize_workspace_path(path).as_posix())
        result = await self._run_helper(
            _GLOB_FILES_HELPER,
            *args,
        )
        try:
            values = json.loads(result.stdout)
            return tuple(values)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

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
            if key in _RESERVED_GUEST_ENV:
                continue
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
