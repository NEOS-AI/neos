# Coding Sandbox Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-independent, secure coding workspace with Memory and Docker providers, bounded workspace tools, portable snapshots, reconnectable PTYs, and filesystem watcher replay.

**Architecture:** `SandboxProvider` and `SandboxSession` protocols isolate the coding loop and future browser gateway from provider details. A fully functional Memory provider is the executable reference contract; a Docker CLI adapter implements the same contract through an injected command runner. Shared path, archive, stream, policy, metrics, and error types prevent provider drift.

**Tech Stack:** Python 3.12, asyncio, Pydantic 2, stdlib subprocess/tarfile/pathlib/pty, Prometheus client, pytest 9, pytest-asyncio; Docker CLI for opt-in integration tests only.

## Global Constraints

- Do not add the Docker Python SDK; Docker access uses an injected standard-library subprocess runner.
- Docker sandboxes run non-root, drop all capabilities, use `no-new-privileges`, a read-only root filesystem, bounded writable workspace/tmp, explicit CPU/memory/PID limits, and network `none` by default.
- Never accept arbitrary host mounts, privileged mode, host PID/IPC, or the Docker socket.
- All workspace paths are POSIX-relative, reject NUL/absolute/traversal paths, resolve symlinks, and remain beneath the workspace root.
- Commands use argument tuples without a shell, an environment allowlist, bounded stdin/output, mandatory timeout, and process-group termination.
- Stream cursors are monotonic; replay is bounded and reports `ReplayGap` instead of silently returning incomplete history.
- Snapshot restore creates a new sandbox and cleans all partial resources on failure.
- Metric labels must be bounded; sandbox, run, task, command, and path identifiers belong in logs/traces, not metric labels.
- Keep `.env.template` and the unrelated untracked documents currently in the worktree out of every commit.
- Docker is unavailable on the current development machine, so the normal suite must pass without it and the real Docker suite must report an explicit skip reason.

## File map

| File | Responsibility |
|---|---|
| `neos/coding/sandbox/base.py` | Domain types, errors, provider/session/snapshot/stream protocols |
| `neos/coding/sandbox/paths.py` | Workspace-relative path normalization and symlink containment |
| `neos/coding/sandbox/streams.py` | Monotonic cursor allocation and bounded async replay |
| `neos/coding/sandbox/archive.py` | Snapshot manifest, safe tar creation, validation, extraction |
| `neos/coding/sandbox/process.py` | Bounded non-shell process execution and process-group cleanup |
| `neos/coding/sandbox/memory.py` | Reference provider, workspace operations, lifecycle, snapshot, PTY, watcher |
| `neos/coding/sandbox/command.py` | Injected Docker CLI runner and sanitized failure mapping |
| `neos/coding/sandbox/docker.py` | Docker lifecycle and session adapter |
| `neos/coding/sandbox/factory.py` | Validated configuration-to-provider construction |
| `neos/config/schema.py` | Nested sandbox configuration schema and fail-closed validators |
| `neos/coding/runtime.py` | Runtime ownership and shutdown wiring for the selected provider |
| `neos/observability/metrics.py` | Bounded sandbox lifecycle/operation/stream metrics |
| `tests/coding/sandbox/conformance.py` | Reusable provider contract scenarios |
| `tests/coding/sandbox/test_*.py` | Unit, security, failure-injection, Memory, and Docker tests |
| `tests/coding/integration/test_docker_sandbox.py` | Opt-in real Docker conformance suite |

---

### Task 1: Domain contracts and lifecycle

**Files:**
- Create: `neos/coding/sandbox/__init__.py`
- Create: `neos/coding/sandbox/base.py`
- Test: `tests/coding/sandbox/test_base.py`

**Interfaces:**
- Consumes: no sandbox code.
- Produces: `SandboxId`, `SandboxState`, `Sandbox`, `SandboxLimits`, `CommandRequest`, `CommandResult`, `FileEntry`, `SearchMatch`, `Snapshot`, `StreamEvent[T]`, `SandboxProvider`, `SandboxSession`, `ReplayStream[T]`, and the six public sandbox errors.

- [ ] **Step 1: Write failing lifecycle and value-object tests**

```python
# tests/coding/sandbox/test_base.py
from datetime import UTC, datetime, timedelta
import pytest

from neos.coding.sandbox.base import (
    CommandRequest, Sandbox, SandboxLimits, SandboxPolicyViolation,
    SandboxState, SandboxStateConflict,
)

NOW = datetime(2026, 7, 19, tzinfo=UTC)

def test_sandbox_allows_only_declared_lifecycle_transitions() -> None:
    sandbox = Sandbox.creating("sb_1", "user_1", SandboxLimits.safe_defaults(), NOW)
    running = sandbox.transition(SandboxState.RUNNING, NOW)
    suspended = running.transition(SandboxState.SUSPENDED, NOW + timedelta(seconds=1))
    assert suspended.transition(SandboxState.RUNNING, NOW + timedelta(seconds=2)).state is SandboxState.RUNNING
    with pytest.raises(SandboxStateConflict):
        sandbox.transition(SandboxState.SUSPENDED, NOW)

def test_command_request_rejects_shell_and_unbounded_input() -> None:
    with pytest.raises(SandboxPolicyViolation):
        CommandRequest(argv=())
    with pytest.raises(SandboxPolicyViolation):
        CommandRequest(argv=("sh", "-c", "echo unsafe"))
```

- [ ] **Step 2: Run the tests and confirm the missing module failure**

Run: `pytest -q tests/coding/sandbox/test_base.py`

Expected: FAIL during collection with `ModuleNotFoundError: neos.coding.sandbox`.

- [ ] **Step 3: Implement immutable domain types, transition table, errors, and async protocols**

```python
# neos/coding/sandbox/base.py (core shape; include every protocol method from the design)
class SandboxError(RuntimeError): pass
class SandboxUnavailable(SandboxError): pass
class SandboxNotFound(SandboxError): pass
class SandboxStateConflict(SandboxError): pass
class SandboxPolicyViolation(SandboxError): pass
class SandboxTimeout(SandboxError): pass
class ReplayGap(SandboxError): pass

class SandboxState(StrEnum):
    CREATING = "creating"
    RUNNING = "running"
    SUSPENDED = "suspended"
    DESTROYED = "destroyed"

_TRANSITIONS = {
    SandboxState.CREATING: {SandboxState.RUNNING, SandboxState.DESTROYED},
    SandboxState.RUNNING: {SandboxState.SUSPENDED, SandboxState.DESTROYED},
    SandboxState.SUSPENDED: {SandboxState.RUNNING, SandboxState.DESTROYED},
    SandboxState.DESTROYED: set(),
}

@dataclass(frozen=True, slots=True)
class Sandbox:
    sandbox_id: str
    owner_id: str
    state: SandboxState
    limits: SandboxLimits
    created_at: datetime
    updated_at: datetime
    workspace_revision: int = 0
    provider: str = "memory"
    image_digest: str | None = None

    def transition(self, target: SandboxState, now: datetime) -> "Sandbox":
        if target not in _TRANSITIONS[self.state]:
            raise SandboxStateConflict(f"{self.state.value}->{target.value}")
        return replace(self, state=target, updated_at=now)
```

Define keyword-only async protocol methods exactly as listed in the design. `CommandRequest.__post_init__` rejects empty argv, `sh|bash|zsh` followed by `-c`, NUL values, non-positive timeouts, and limit overflow. Keep output truncation flags separate in `CommandResult`.

- [ ] **Step 4: Run focused tests and type/import smoke checks**

Run: `pytest -q tests/coding/sandbox/test_base.py && python -c 'from neos.coding.sandbox.base import SandboxProvider, SandboxSession'`

Expected: all tests PASS and the import exits 0.

- [ ] **Step 5: Commit the contract**

```bash
git add neos/coding/sandbox/__init__.py neos/coding/sandbox/base.py tests/coding/sandbox/test_base.py
git commit -m "feat: define coding sandbox contracts"
```

### Task 2: Workspace path security

**Files:**
- Create: `neos/coding/sandbox/paths.py`
- Test: `tests/coding/sandbox/test_paths.py`

**Interfaces:**
- Consumes: `SandboxPolicyViolation` from Task 1.
- Produces: `normalize_workspace_path(path: str) -> PurePosixPath` and `resolve_workspace_path(root: Path, path: str, *, allow_missing_leaf: bool = False) -> Path`.

- [ ] **Step 1: Write traversal and symlink-escape tests**

```python
@pytest.mark.parametrize("value", ["/etc/passwd", "../secret", "a/../../secret", "bad\0name"])
def test_normalize_rejects_paths_outside_workspace(value: str) -> None:
    with pytest.raises(SandboxPolicyViolation):
        normalize_workspace_path(value)

def test_resolve_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("secret")
    (tmp_path / "escape").symlink_to(outside)
    with pytest.raises(SandboxPolicyViolation):
        resolve_workspace_path(tmp_path, "escape")

def test_missing_write_leaf_is_allowed_only_below_real_parent(tmp_path: Path) -> None:
    assert resolve_workspace_path(tmp_path, "src/new.py", allow_missing_leaf=True) == tmp_path / "src/new.py"
```

- [ ] **Step 2: Verify tests fail because the functions do not exist**

Run: `pytest -q tests/coding/sandbox/test_paths.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement lexical normalization and component-by-component containment**

```python
def normalize_workspace_path(path: str) -> PurePosixPath:
    if "\0" in path or path.startswith("/"):
        raise SandboxPolicyViolation("invalid_workspace_path")
    candidate = PurePosixPath(path or ".")
    if any(part == ".." for part in candidate.parts):
        raise SandboxPolicyViolation("workspace_path_escape")
    return candidate

def resolve_workspace_path(root: Path, path: str, *, allow_missing_leaf: bool = False) -> Path:
    relative = normalize_workspace_path(path)
    root_real = root.resolve(strict=True)
    candidate = root_real.joinpath(*relative.parts)
    probe = candidate.parent if allow_missing_leaf and not candidate.exists() else candidate
    resolved = probe.resolve(strict=not allow_missing_leaf)
    if not resolved.is_relative_to(root_real):
        raise SandboxPolicyViolation("workspace_symlink_escape")
    return candidate
```

Add protected `.git/config`, `.git/hooks`, and credential/helper path policy for mutation while allowing read-only Git inspection.

- [ ] **Step 4: Run security tests**

Run: `pytest -q tests/coding/sandbox/test_paths.py`

Expected: PASS.

- [ ] **Step 5: Commit path policy**

```bash
git add neos/coding/sandbox/paths.py tests/coding/sandbox/test_paths.py
git commit -m "feat: secure sandbox workspace paths"
```

### Task 3: Bounded cursor replay streams

**Files:**
- Create: `neos/coding/sandbox/streams.py`
- Test: `tests/coding/sandbox/test_streams.py`

**Interfaces:**
- Consumes: `ReplayGap`, `StreamEvent[T]`, `ReplayStream[T]` from Task 1.
- Produces: `BoundedReplayStream[T](max_events: int, max_bytes: int, size_of: Callable[[T], int])` with `publish`, `replay`, `subscribe`, and `close`.

- [ ] **Step 1: Write cursor, eviction, replay-gap, and slow-subscriber tests**

```python
async def test_replay_stream_orders_and_replays_after_cursor() -> None:
    stream = BoundedReplayStream[str](max_events=3, max_bytes=20, size_of=len)
    one = await stream.publish("one")
    two = await stream.publish("two")
    assert [event.value for event in await stream.replay(after_cursor=one.cursor)] == ["two"]
    assert two.cursor == one.cursor + 1

async def test_evicted_cursor_raises_replay_gap() -> None:
    stream = BoundedReplayStream[str](max_events=2, max_bytes=20, size_of=len)
    first = await stream.publish("one")
    await stream.publish("two")
    await stream.publish("three")
    with pytest.raises(ReplayGap):
        await stream.replay(after_cursor=first.cursor - 1)
```

- [ ] **Step 2: Verify the focused tests fail**

Run: `pytest -q tests/coding/sandbox/test_streams.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement lock-protected monotonic cursors and bounded subscriber queues**

```python
class BoundedReplayStream(Generic[T]):
    async def publish(self, value: T) -> StreamEvent[T]:
        async with self._lock:
            if self._closed:
                raise SandboxStateConflict("stream_closed")
            self._cursor += 1
            event = StreamEvent(cursor=self._cursor, value=value)
            self._events.append(event)
            self._bytes += self._size_of(value)
            self._evict_to_limits()
            for queue in self._subscribers:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(event)
            return event

    async def replay(self, *, after_cursor: int) -> tuple[StreamEvent[T], ...]:
        async with self._lock:
            if self._events and after_cursor < self._events[0].cursor - 1:
                raise ReplayGap(f"cursor {after_cursor} was evicted")
            return tuple(event for event in self._events if event.cursor > after_cursor)
```

`subscribe(after_cursor)` must replay under the same lock used to register the queue so no event can fall between replay and live subscription. `close` publishes a terminal state to subscribers and is idempotent.

- [ ] **Step 4: Run stream tests repeatedly to catch scheduling races**

Run: `pytest -q tests/coding/sandbox/test_streams.py --count=10` if `pytest-repeat` is installed; otherwise run `for i in 1 2 3 4 5; do pytest -q tests/coding/sandbox/test_streams.py || exit 1; done`.

Expected: every run PASS.

- [ ] **Step 5: Commit replay streams**

```bash
git add neos/coding/sandbox/streams.py tests/coding/sandbox/test_streams.py
git commit -m "feat: add bounded sandbox replay streams"
```

### Task 4: Bounded local process and Memory workspace tools

**Files:**
- Create: `neos/coding/sandbox/process.py`
- Create: `neos/coding/sandbox/memory.py`
- Create: `tests/coding/sandbox/conformance.py`
- Test: `tests/coding/sandbox/test_process.py`
- Test: `tests/coding/sandbox/test_memory_workspace.py`

**Interfaces:**
- Consumes: Task 1 contracts and Task 2 path functions.
- Produces: `BoundedProcessRunner.run(request, *, cwd, env) -> CommandResult`, `MemorySandboxProvider`, and the conformance fixture protocol `provider_factory(tmp_path) -> SandboxProvider`.

- [ ] **Step 1: Write failing process-bound and workspace-operation tests**

```python
async def test_process_timeout_kills_child_group(tmp_path: Path) -> None:
    result = await BoundedProcessRunner().run(
        CommandRequest(argv=(sys.executable, "-c", "import time; time.sleep(5)"), timeout_sec=0.05),
        cwd=tmp_path, env={},
    )
    assert result.timed_out is True
    assert result.exit_code is None

async def test_memory_session_reads_searches_and_reports_git(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/app.py", b"print('needle')\n")
    assert await session.read_file("src/app.py") == b"print('needle')\n"
    matches = await session.search_text("needle", paths=("src/**",), regex=False, limit=10)
    assert [(m.path, m.line) for m in matches] == [("src/app.py", 1)]
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `pytest -q tests/coding/sandbox/test_process.py tests/coding/sandbox/test_memory_workspace.py`

Expected: FAIL on missing implementations.

- [ ] **Step 3: Implement bounded subprocess execution**

Use `asyncio.create_subprocess_exec(*request.argv, start_new_session=True)` with `shell=False`. Feed bounded stdin through `communicate`; wrap it in `asyncio.timeout`. On timeout call `os.killpg(process.pid, signal.SIGKILL)`, await the process, and return `timed_out=True`. Slice stdout/stderr to their independent maximums and set truncation flags before decoding with replacement.

```python
async with asyncio.timeout(request.timeout_sec):
    stdout, stderr = await process.communicate(request.stdin)
return CommandResult(
    exit_code=process.returncode,
    stdout=stdout[:request.max_output_bytes],
    stderr=stderr[:request.max_output_bytes],
    stdout_truncated=len(stdout) > request.max_output_bytes,
    stderr_truncated=len(stderr) > request.max_output_bytes,
    timed_out=False,
)
```

- [ ] **Step 4: Implement Memory lifecycle and workspace methods minimally**

Store sandbox records behind an `asyncio.Lock`, allocate one `TemporaryDirectory` per sandbox below the injected root, require `RUNNING` before opening or using sessions, and make destroy idempotent. Implement list/stat/read/write with Task 2 validation, bounded Python regex/literal search, read-only Git commands through `BoundedProcessRunner`, and generic command execution with an environment allowlist. Increment workspace revision once per successful mutation.

- [ ] **Step 5: Run process, Memory, and initial conformance tests**

Run: `pytest -q tests/coding/sandbox/test_process.py tests/coding/sandbox/test_memory_workspace.py`

Expected: PASS.

- [ ] **Step 6: Commit the executable Memory workspace**

```bash
git add neos/coding/sandbox/process.py neos/coding/sandbox/memory.py tests/coding/sandbox/conformance.py tests/coding/sandbox/test_process.py tests/coding/sandbox/test_memory_workspace.py
git commit -m "feat: execute bounded memory sandbox tools"
```

### Task 5: Portable snapshot, restore, suspend, and resume

**Files:**
- Create: `neos/coding/sandbox/archive.py`
- Modify: `neos/coding/sandbox/memory.py`
- Test: `tests/coding/sandbox/test_archive.py`
- Test: `tests/coding/sandbox/test_memory_lifecycle.py`

**Interfaces:**
- Consumes: `Snapshot`, Memory provider state, Task 2 path policy.
- Produces: `SnapshotManifest`, `LocalSnapshotStore`, `create_workspace_archive`, `extract_workspace_archive`, and working Memory `snapshot/restore/suspend/resume`.

- [ ] **Step 1: Write unsafe-archive and restore-isolation tests**

```python
def test_extract_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = make_tar(tmp_path, name="../../escape", payload=b"owned")
    with pytest.raises(SandboxPolicyViolation):
        extract_workspace_archive(archive, tmp_path / "target", max_expanded_bytes=1024)

async def test_restore_creates_independent_running_sandbox(provider) -> None:
    source = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    session = await provider.open_session(source.sandbox_id)
    await session.write_file("answer.txt", b"42")
    snapshot = await provider.snapshot(source.sandbox_id)
    restored = await provider.restore(snapshot.snapshot_id, owner_id="u1")
    assert restored.sandbox_id != source.sandbox_id
    assert restored.state is SandboxState.RUNNING
    assert await (await provider.open_session(restored.sandbox_id)).read_file("answer.txt") == b"42"
```

- [ ] **Step 2: Verify the new tests fail**

Run: `pytest -q tests/coding/sandbox/test_archive.py tests/coding/sandbox/test_memory_lifecycle.py`

Expected: FAIL on missing archive/store operations.

- [ ] **Step 3: Implement deterministic manifest and safe tar handling**

Create archives through a temporary file, sort entries, exclude configured secret/cache/socket/device patterns, hash the final archive with SHA-256, then atomically rename it next to `manifest.json`. On extraction, reject absolute/traversing names, devices, FIFOs, sockets, escaping hard/symbolic links, entry-count overflow, and compressed/expanded size overflow before writing any entry.

```python
@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    schema_version: int
    source_sandbox_id: str
    workspace_revision: int
    created_at: datetime
    base_image_digest: str | None
    content_checksum: str
```

- [ ] **Step 4: Add write fencing and compensating restore cleanup**

Use the sandbox record lock as the snapshot write fence. Restore validates manifest version, digest compatibility, and checksum before extraction. If create or extraction fails, call `destroy(new_id)` in `finally` unless the sandbox reached a fully validated `RUNNING` state. Suspend transitions `RUNNING→SUSPENDED`; resume transitions back and rejects session work while suspended.

- [ ] **Step 5: Run archive and lifecycle tests**

Run: `pytest -q tests/coding/sandbox/test_archive.py tests/coding/sandbox/test_memory_lifecycle.py tests/coding/sandbox/test_memory_workspace.py`

Expected: PASS.

- [ ] **Step 6: Commit durable workspace lifecycle**

```bash
git add neos/coding/sandbox/archive.py neos/coding/sandbox/memory.py tests/coding/sandbox/test_archive.py tests/coding/sandbox/test_memory_lifecycle.py
git commit -m "feat: snapshot and resume coding sandboxes"
```

### Task 6: Reconnectable PTY and normalized filesystem watcher

**Files:**
- Modify: `neos/coding/sandbox/memory.py`
- Modify: `neos/coding/sandbox/streams.py`
- Test: `tests/coding/sandbox/test_memory_pty.py`
- Test: `tests/coding/sandbox/test_memory_watcher.py`

**Interfaces:**
- Consumes: `BoundedReplayStream`, workspace revision, lifecycle state.
- Produces: `PtyOutput`, `PtyClosed`, `WorkspaceChangeBatch`, `WorkspaceChangeKind`, and complete Memory session PTY/watcher methods.

- [ ] **Step 1: Write PTY reconnect, resize, and lifecycle-close tests**

```python
async def test_pty_replays_output_after_disconnect(memory_session) -> None:
    pty = await memory_session.create_pty(argv=("/bin/sh",))
    await memory_session.write_pty(pty.pty_id, b"printf reconnectable\\n")
    first = await wait_for_output(pty, contains=b"reconnectable")
    replay = await pty.replay(after_cursor=first.cursor - 1)
    assert replay[-1].value.data.endswith(b"reconnectable\r\n")

async def test_suspend_closes_runtime_pty(provider, running_sandbox, memory_session) -> None:
    pty = await memory_session.create_pty(argv=("/bin/sh",))
    await provider.suspend(running_sandbox.sandbox_id)
    assert (await pty.wait_closed()).reason == "sandbox_suspended"
```

- [ ] **Step 2: Write watcher debounce, revision, noise, and overflow tests**

```python
async def test_watcher_coalesces_changes_and_carries_revision(memory_session) -> None:
    watcher = await memory_session.watch_files(after_cursor=0)
    await memory_session.write_file("src/a.py", b"one")
    await memory_session.write_file("src/a.py", b"two")
    batch = await anext(watcher)
    assert batch.changes[-1].path == "src/a.py"
    assert batch.workspace_revision == 2

async def test_watcher_gap_requires_workspace_resync(memory_session) -> None:
    watcher = await memory_session.watch_files(after_cursor=0)
    await overflow_replay_buffer(memory_session)
    with pytest.raises(ReplayGap):
        await watcher.replay(after_cursor=0)
```

- [ ] **Step 3: Implement PTY ownership and replay**

On POSIX, create a master/slave pair with `pty.openpty`, spawn with the slave attached to stdin/stdout/stderr and `start_new_session=True`, then publish bounded master reads to a replay stream. Validate input size/rate and resize dimensions; use `fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))`. Disconnect only removes a subscriber. Kill, process exit, suspend, idle expiry, and destroy publish one terminal event and reap the process group.

- [ ] **Step 4: Implement provider-normalized watcher batches**

For Memory, record mutations performed through session methods immediately and run a bounded periodic directory reconciliation to detect external process changes. Normalize paths, ignore `.git/**`, swap files, and internal metadata; debounce/coalesce by path; increment the observed revision; publish cursor batches. Directory scan failure or excessive changes emits `watch_overflow` and `workspace_invalidated`.

- [ ] **Step 5: Run PTY/watcher tests and check for leaked processes/tasks**

Run: `pytest -q tests/coding/sandbox/test_memory_pty.py tests/coding/sandbox/test_memory_watcher.py -W error::pytest.PytestUnraisableExceptionWarning`

Expected: PASS with no pending-task, resource, or unraisable warnings.

- [ ] **Step 6: Commit streaming workspace state**

```bash
git add neos/coding/sandbox/memory.py neos/coding/sandbox/streams.py tests/coding/sandbox/test_memory_pty.py tests/coding/sandbox/test_memory_watcher.py
git commit -m "feat: stream sandbox terminal and file changes"
```

### Task 7: Docker CLI command policy

**Files:**
- Create: `neos/coding/sandbox/command.py`
- Test: `tests/coding/sandbox/test_docker_command.py`

**Interfaces:**
- Consumes: `SandboxTimeout`, `SandboxUnavailable`, bounded process semantics.
- Produces: `DockerCommand`, `DockerCommandResult`, `DockerCommandRunner.run(*args: str, timeout_sec: float) -> DockerCommandResult`, and `build_create_args(*, sandbox_id: str, image: str, limits: SandboxLimits, network_mode: str = "none", allow_unpinned_image: bool = False) -> tuple[str, ...]`.

- [ ] **Step 1: Write exact security-flag and sanitized-error tests**

```python
def test_create_args_enforce_isolation() -> None:
    args = build_create_args(sandbox_id="sb_1", image="neos-sandbox@sha256:" + "a" * 64, limits=LIMITS)
    joined = " ".join(args)
    assert "--user 10001:10001" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in args
    assert "--network none" in joined
    assert "--pids-limit" in args
    assert "/var/run/docker.sock" not in joined
    assert "--privileged" not in args

async def test_runner_maps_timeout_without_leaking_stderr(fake_process) -> None:
    fake_process.raise_timeout = True
    with pytest.raises(SandboxTimeout) as error:
        await DockerCommandRunner(exec=fake_process).run("inspect", "sb_1", timeout_sec=1)
    assert "registry-token" not in str(error.value)
```

- [ ] **Step 2: Run the command-policy tests**

Run: `pytest -q tests/coding/sandbox/test_docker_command.py`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement argv-only Docker runner and builders**

The runner calls `create_subprocess_exec("docker", *args)` and never a shell. Map missing CLI/non-zero daemon transport failures to `SandboxUnavailable`, timeouts to `SandboxTimeout`, and retain sanitized exit category only. `build_create_args` pins labels, user, capabilities, security option, read-only root, tmpfs, network, CPU, memory, PID, and workspace volume policy. Reject non-digest images unless `allow_unpinned_image=True` is explicitly supplied by development configuration.

- [ ] **Step 4: Run unit tests and inspect representative argv**

Run: `pytest -q tests/coding/sandbox/test_docker_command.py -vv`

Expected: PASS; test output contains no credential or raw Docker stderr.

- [ ] **Step 5: Commit Docker command boundary**

```bash
git add neos/coding/sandbox/command.py tests/coding/sandbox/test_docker_command.py
git commit -m "feat: enforce docker sandbox command policy"
```

### Task 8: Docker provider and failure compensation

**Files:**
- Create: `neos/coding/sandbox/docker.py`
- Test: `tests/coding/sandbox/test_docker_provider.py`
- Test: `tests/coding/sandbox/test_docker_failures.py`

**Interfaces:**
- Consumes: all contracts, archive tools, Docker runner/builders.
- Produces: `DockerSandboxProvider` and `DockerSandboxSession` matching the Memory provider's public contract.

- [ ] **Step 1: Write scripted-runner lifecycle and rediscovery tests**

```python
async def test_create_is_running_only_after_readiness(scripted_runner) -> None:
    scripted_runner.expect("create", result="container-id")
    scripted_runner.expect("start", result="")
    scripted_runner.expect("exec", result="ready")
    provider = DockerSandboxProvider(runner=scripted_runner, config=DOCKER_CONFIG)
    sandbox = await provider.create(owner_id="u1", limits=LIMITS)
    assert sandbox.state is SandboxState.RUNNING
    scripted_runner.assert_exhausted()

async def test_provider_rediscovers_only_owned_labeled_containers(scripted_runner) -> None:
    scripted_runner.return_labeled_inspect([owned_container_json(), unrelated_container_json()])
    provider = DockerSandboxProvider(runner=scripted_runner, config=DOCKER_CONFIG)
    assert [item.sandbox_id for item in await provider.reconcile()] == ["sb_owned"]
```

- [ ] **Step 2: Write reverse-cleanup, idempotent-destroy, and stale-transition tests**

```python
async def test_readiness_failure_removes_partial_container(scripted_runner) -> None:
    scripted_runner.fail_on("exec")
    provider = DockerSandboxProvider(runner=scripted_runner, config=DOCKER_CONFIG)
    with pytest.raises(SandboxUnavailable):
        await provider.create(owner_id="u1", limits=LIMITS)
    assert scripted_runner.calls[-1][:2] == ("rm", "--force")

async def test_destroy_attempts_volume_cleanup_when_container_is_missing(scripted_runner) -> None:
    provider = DockerSandboxProvider(runner=scripted_runner, config=DOCKER_CONFIG)
    await provider.destroy("sb_missing")
    await provider.destroy("sb_missing")
    assert scripted_runner.only_cleanup_or_inspect_calls()
```

- [ ] **Step 3: Implement lifecycle, labels, readiness, and reconciliation**

Keep provider metadata behind a lock and use a per-sandbox operation lock. Create resources in volume→container→start→probe order and compensate in reverse. Suspend uses `docker stop`, resume uses `docker start` plus readiness. Destroy tries process/PTY cleanup, container removal, and volume removal even if an earlier stage says not found. Rediscovery parses only labels under the NEOS namespace and reaps items past absolute TTL.

- [ ] **Step 4: Implement Docker workspace/session operations**

Validate every path before constructing an exec request. Use a small fixed Python helper command inside the pinned image for binary file/tree/stat operations, bounded `rg` for search, read-only `git` subcommands, and direct argv execution for commands. Transfer snapshot archives over stdin/stdout with explicit size limits; never interpolate paths into shell strings. PTY uses `docker exec -i` attached to the provider's replay stream; Docker does not expose terminal detach semantics to consumers.

- [ ] **Step 5: Run all Docker unit and failure-injection tests**

Run: `pytest -q tests/coding/sandbox/test_docker_command.py tests/coding/sandbox/test_docker_provider.py tests/coding/sandbox/test_docker_failures.py`

Expected: PASS without requiring a Docker daemon.

- [ ] **Step 6: Commit the Docker provider**

```bash
git add neos/coding/sandbox/docker.py tests/coding/sandbox/test_docker_provider.py tests/coding/sandbox/test_docker_failures.py
git commit -m "feat: add docker coding sandbox provider"
```

### Task 9: Fail-closed configuration, runtime wiring, metrics, and audit metadata

**Files:**
- Create: `neos/coding/sandbox/factory.py`
- Modify: `neos/config/schema.py`
- Modify: `neos/coding/runtime.py`
- Modify: `neos/observability/metrics.py`
- Modify: `config/neos.default.yaml`
- Modify: `config/neos.development.yaml`
- Modify: `config/neos.production.yaml`
- Test: `tests/config/test_sandbox_config.py`
- Test: `tests/coding/sandbox/test_factory.py`
- Test: `tests/coding/sandbox/test_observability.py`

**Interfaces:**
- Consumes: Memory/Docker providers and global `settings`/`metrics` patterns.
- Produces: nested sandbox config models, `create_sandbox_provider(config, metrics, audit_sink)`, `CodingRuntime.sandboxes`, and bounded Prometheus instruments.

- [ ] **Step 1: Write configuration validation tests**

```python
def test_development_defaults_to_memory_provider() -> None:
    config = AppConfig.model_validate({"environment": "development"})
    assert config.sandbox.provider == "memory"

@pytest.mark.parametrize("sandbox", [
    {"provider": "docker", "docker": {"image": "neos:latest"}},
    {"provider": "docker", "docker": {"image": DIGEST_IMAGE, "network_mode": "bridge"}},
])
def test_production_rejects_unsafe_docker_configuration(sandbox) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"environment": "production", "sandbox": sandbox})
```

- [ ] **Step 2: Write factory, runtime ownership, metric-label, and audit-redaction tests**

```python
def test_factory_selects_memory_provider(tmp_path: Path) -> None:
    provider = create_sandbox_provider(memory_config(tmp_path), metrics=NoopMetrics(), audit_sink=RecordingAudit())
    assert isinstance(provider, MemorySandboxProvider)

def test_sandbox_metrics_use_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())
    assert collector.coding_sandbox_lifecycle_seconds._labelnames == ("provider", "operation", "outcome")
    assert collector.coding_sandbox_stream_total._labelnames == ("stream", "outcome")

def test_audit_event_does_not_capture_contents() -> None:
    event = SandboxAuditEvent.for_command(argv=("python", "secret.py"), env={"TOKEN": "secret"}, outcome="ok")
    assert "secret" not in json.dumps(asdict(event))
```

- [ ] **Step 3: Replace the flat `SandboxConfig` with nested strict models**

```python
class SandboxLifecycleConfig(StrictConfigModel):
    create_timeout_sec: float = Field(default=30, gt=0, le=300)
    idle_timeout_sec: float = Field(default=900, gt=0)
    max_lifetime_sec: float = Field(default=14400, gt=0)

class SandboxConfig(StrictConfigModel):
    enabled: bool = False
    provider: Literal["memory", "docker"] = "memory"
    lifecycle: SandboxLifecycleConfig = Field(default_factory=SandboxLifecycleConfig)
    resources: SandboxResourceConfig = Field(default_factory=SandboxResourceConfig)
    execution: SandboxExecutionConfig = Field(default_factory=SandboxExecutionConfig)
    streams: SandboxStreamConfig = Field(default_factory=SandboxStreamConfig)
    docker: SandboxDockerConfig = Field(default_factory=SandboxDockerConfig)
```

Add cross-field validation at `AppConfig`: production Docker requires a `sha256` image digest, `network_mode == "none"`, non-root user, and all positive limits; `idle_timeout_sec <= max_lifetime_sec`; hard command timeout cannot exceed maximum sandbox lifetime. Preserve legacy `SANDBOX_` environment mapping through the existing prefix mechanism.

- [ ] **Step 4: Build provider factory and runtime shutdown ownership**

Add `sandboxes: SandboxProvider` to `CodingRuntime`. `create_coding_runtime` accepts an optional injected provider for tests and otherwise uses the factory. Runtime shutdown must close watcher/PTY tasks, then destroy or suspend according to configured development policy. Do not attach sandbox state to module-level API handlers in this phase.

- [ ] **Step 5: Add bounded metrics and structured audit events**

Add histograms/counters/gauges for lifecycle, operations, active states, snapshot, PTY, and watcher outcomes. Labels are only provider/operation/outcome/stream/error_code. `SandboxAuditEvent` stores IDs in structured logs, command executable category rather than argv, byte counts rather than contents, and environment variable names rather than values.

- [ ] **Step 6: Run configuration, factory, runtime regression, and metric tests**

Run: `pytest -q tests/config/test_sandbox_config.py tests/config/test_config_schema.py tests/coding/sandbox/test_factory.py tests/coding/sandbox/test_observability.py tests/coding/test_durability_metrics.py tests/coding/test_development_supervisor_vertical_slice.py tests/coding/test_celery_worker_vertical_slice.py`

Expected: PASS; existing coding runtime construction remains compatible through optional injection.

- [ ] **Step 7: Commit configuration and wiring**

```bash
git add neos/coding/sandbox/factory.py neos/config/schema.py neos/coding/runtime.py neos/observability/metrics.py config/neos.default.yaml config/neos.development.yaml config/neos.production.yaml tests/config/test_sandbox_config.py tests/coding/sandbox/test_factory.py tests/coding/sandbox/test_observability.py
git commit -m "feat: wire secure coding sandbox runtime"
```

### Task 10: Shared conformance suite and opt-in real Docker verification

**Files:**
- Modify: `tests/coding/sandbox/conformance.py`
- Create: `tests/coding/sandbox/test_memory_conformance.py`
- Create: `tests/coding/integration/test_docker_sandbox.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: complete provider contract and both implementations.
- Produces: reusable `SandboxProviderConformance` test mixin and documented local/CI verification commands.

- [ ] **Step 1: Complete provider-independent conformance scenarios**

```python
class SandboxProviderConformance:
    async def test_lifecycle_and_idempotent_destroy(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        assert sandbox.state is SandboxState.RUNNING
        assert (await provider.suspend(sandbox.sandbox_id)).state is SandboxState.SUSPENDED
        assert (await provider.resume(sandbox.sandbox_id)).state is SandboxState.RUNNING
        await provider.destroy(sandbox.sandbox_id)
        await provider.destroy(sandbox.sandbox_id)

    async def test_file_search_git_and_bounded_command(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        session = await provider.open_session(sandbox.sandbox_id)
        await session.write_file("main.py", b"print('contract')\n")
        assert await session.read_file("main.py") == b"print('contract')\n"
        assert (await session.search_text("contract", paths=("**/*.py",), regex=False, limit=5))[0].line == 1
        result = await session.execute(CommandRequest(argv=("python", "main.py"), timeout_sec=5))
        assert result.exit_code == 0 and result.stdout == b"contract\n"

    async def test_suspend_blocks_sessions_and_resume_restores_access(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        session = await provider.open_session(sandbox.sandbox_id)
        await provider.suspend(sandbox.sandbox_id)
        with pytest.raises(SandboxStateConflict):
            await session.list_tree(".")
        await provider.resume(sandbox.sandbox_id)
        assert await session.list_tree(".") == ()

    async def test_snapshot_restore_is_independent(self, provider):
        source = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        await (await provider.open_session(source.sandbox_id)).write_file("state.txt", b"v1")
        snapshot = await provider.snapshot(source.sandbox_id)
        restored = await provider.restore(snapshot.snapshot_id, owner_id="u1")
        restored_session = await provider.open_session(restored.sandbox_id)
        await restored_session.write_file("state.txt", b"v2")
        assert await (await provider.open_session(source.sandbox_id)).read_file("state.txt") == b"v1"

    async def test_pty_reconnect_and_replay_gap(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        session = await provider.open_session(sandbox.sandbox_id)
        terminal = await session.create_pty(argv=("/bin/sh",))
        await session.write_pty(terminal.pty_id, b"printf conformance\\n")
        output = await wait_for_output(terminal, contains=b"conformance")
        assert (await terminal.replay(after_cursor=output.cursor - 1))[-1].cursor == output.cursor
        await force_stream_eviction(terminal)
        with pytest.raises(ReplayGap):
            await terminal.replay(after_cursor=0)

    async def test_watcher_revision_overflow_and_resync(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        session = await provider.open_session(sandbox.sandbox_id)
        watcher = await session.watch_files(after_cursor=0)
        await session.write_file("change.txt", b"one")
        batch = await anext(watcher)
        assert batch.workspace_revision == 1
        await force_watcher_overflow(session)
        invalidation = await wait_for_change(watcher, kind=WorkspaceChangeKind.WORKSPACE_INVALIDATED)
        assert invalidation.workspace_revision >= batch.workspace_revision

    async def test_traversal_symlink_and_environment_policy(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        session = await provider.open_session(sandbox.sandbox_id)
        with pytest.raises(SandboxPolicyViolation):
            await session.read_file("../../etc/passwd")
        with pytest.raises(SandboxPolicyViolation):
            await session.execute(CommandRequest(argv=("env",), env={"TOKEN": "secret"}))

    async def test_concurrent_state_transition_has_one_winner(self, provider):
        sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
        outcomes = await asyncio.gather(
            provider.suspend(sandbox.sandbox_id),
            provider.destroy(sandbox.sandbox_id),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in outcomes) == 1
        assert sum(isinstance(item, SandboxStateConflict) for item in outcomes) == 1
```

Implement `wait_for_output`, `force_stream_eviction`, `force_watcher_overflow`, and `wait_for_change` in this same file as bounded async test helpers that fail under `asyncio.timeout(5)`. Share only setup mechanics; keep expected behavior provider-independent.

- [ ] **Step 2: Bind the required Memory conformance suite**

```python
class TestMemorySandboxConformance(SandboxProviderConformance):
    @pytest.fixture
    async def provider(self, tmp_path):
        async with MemorySandboxProvider(root=tmp_path) as provider:
            yield provider
```

Run: `pytest -q tests/coding/sandbox/test_memory_conformance.py`

Expected: PASS.

- [ ] **Step 3: Bind the opt-in Docker suite with an explicit skip reason**

```python
DOCKER_ENABLED = os.getenv("CODING_TEST_DOCKER") == "1"

pytestmark = pytest.mark.skipif(
    not DOCKER_ENABLED or shutil.which("docker") is None,
    reason="set CODING_TEST_DOCKER=1 and install Docker to run sandbox conformance",
)

class TestDockerSandboxConformance(SandboxProviderConformance):
    @pytest.fixture
    async def provider(self, docker_test_config):
        async with DockerSandboxProvider.from_config(docker_test_config) as provider:
            yield provider
```

Run: `pytest -q tests/coding/integration/test_docker_sandbox.py -rs`

Expected on the current machine: SKIP with the exact installation/flag reason. Expected on Docker CI: PASS with `CODING_TEST_DOCKER=1`.

- [ ] **Step 4: Update roadmap status and operational test instructions**

In `docs/NEOS_CODING.md`, mark the sandbox foundation deliverables implemented, link the design spec, document the Memory command and the opt-in Docker command, and leave real model loop and browser REST/WS as the next separate projects.

- [ ] **Step 5: Run sandbox security and conformance suites**

Run: `pytest -q tests/coding/sandbox tests/coding/integration/test_docker_sandbox.py -rs`

Expected: all Memory/unit tests PASS and the real Docker test is explicitly SKIPPED on this machine.

- [ ] **Step 6: Run formatting/static checks for touched Python files**

Run: `ruff check neos/coding/sandbox neos/config/schema.py neos/coding/runtime.py neos/observability/metrics.py tests/coding/sandbox tests/coding/integration/test_docker_sandbox.py`

Expected: `All checks passed!`.

- [ ] **Step 7: Run the complete regression suite**

Run: `pytest -q`

Expected: all tests PASS; only environment-gated Postgres and Docker tests may skip with their documented reasons.

- [ ] **Step 8: Verify diff integrity and commit final conformance/docs**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended sandbox changes plus the user's pre-existing `.env.template` and unrelated untracked documents appear.

```bash
git add tests/coding/sandbox/conformance.py tests/coding/sandbox/test_memory_conformance.py tests/coding/integration/test_docker_sandbox.py docs/NEOS_CODING.md
git commit -m "test: verify coding sandbox providers"
```

## Execution checkpoints

- After Task 3: review public types and cursor semantics before implementations depend on them.
- After Task 6: review Memory conformance, process cleanup, snapshot safety, and async-task leaks.
- After Task 8: review every constructed Docker argv and every compensation path before runtime wiring.
- After Task 10: run `superpowers:requesting-code-review`, address verified findings, then run `superpowers:verification-before-completion` before claiming completion.
