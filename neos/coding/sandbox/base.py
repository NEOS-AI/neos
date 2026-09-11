from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable


class SandboxError(RuntimeError):
    """Base class for sanitized, provider-independent sandbox failures."""


class SandboxUnavailable(SandboxError):
    """The configured provider or its requested capacity is unavailable."""


class SandboxNotFound(SandboxError):
    """The requested sandbox resource does not exist."""


class SandboxStateConflict(SandboxError):
    """An operation conflicts with the sandbox's current lifecycle state."""


class SandboxPolicyViolation(SandboxError):
    """An input violates workspace isolation or execution policy."""


class SandboxTimeout(SandboxError):
    """A bounded sandbox operation exceeded its deadline."""


class ReplayGap(SandboxError):
    """The requested stream cursor has already been evicted."""


class SandboxState(StrEnum):
    CREATING = "creating"
    RUNNING = "running"
    SUSPENDED = "suspended"
    DESTROYED = "destroyed"


_TRANSITIONS = {
    SandboxState.CREATING: {SandboxState.RUNNING, SandboxState.DESTROYED},
    SandboxState.RUNNING: {
        SandboxState.SUSPENDED,
        SandboxState.DESTROYED,
    },
    SandboxState.SUSPENDED: {
        SandboxState.RUNNING,
        SandboxState.DESTROYED,
    },
    SandboxState.DESTROYED: set(),
}


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    cpu_count: float
    memory_bytes: int
    pids: int
    workspace_bytes: int
    command_timeout_sec: float
    max_output_bytes: int
    max_stdin_bytes: int

    @classmethod
    def safe_defaults(cls) -> SandboxLimits:
        return cls(
            cpu_count=1.0,
            memory_bytes=512 * 1024 * 1024,
            pids=128,
            workspace_bytes=1024 * 1024 * 1024,
            command_timeout_sec=30.0,
            max_output_bytes=1024 * 1024,
            max_stdin_bytes=1024 * 1024,
        )


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
    idle_expires_at: datetime | None = None
    expires_at: datetime | None = None
    healthy: bool = True
    last_error_code: str | None = None

    @classmethod
    def creating(
        cls,
        sandbox_id: str,
        owner_id: str,
        limits: SandboxLimits,
        now: datetime,
        *,
        provider: str = "memory",
        image_digest: str | None = None,
        idle_expires_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> Sandbox:
        return cls(
            sandbox_id=sandbox_id,
            owner_id=owner_id,
            state=SandboxState.CREATING,
            limits=limits,
            created_at=now,
            updated_at=now,
            provider=provider,
            image_digest=image_digest,
            idle_expires_at=idle_expires_at,
            expires_at=expires_at,
        )

    def transition(self, target: SandboxState, now: datetime) -> Sandbox:
        if target not in _TRANSITIONS[self.state]:
            raise SandboxStateConflict(
                f"{self.state.value}->{target.value}"
            )
        return replace(self, state=target, updated_at=now)


_SHELLS = {"sh", "bash", "zsh"}


@dataclass(frozen=True, slots=True)
class CommandRequest:
    argv: tuple[str, ...]
    cwd: str = "."
    env: Mapping[str, str] = field(default_factory=dict)
    stdin: bytes = b""
    timeout_sec: float = 30.0
    max_output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if not self.argv:
            raise SandboxPolicyViolation("command_argv_empty")
        if any("\0" in value for value in self.argv):
            raise SandboxPolicyViolation("command_argv_contains_nul")
        executable = self.argv[0].rsplit("/", 1)[-1]
        if (
            executable in _SHELLS
            and len(self.argv) > 1
            and self.argv[1] == "-c"
        ):
            raise SandboxPolicyViolation("shell_command_not_allowed")
        if self.timeout_sec <= 0:
            raise SandboxPolicyViolation("command_timeout_must_be_positive")
        if self.max_output_bytes <= 0:
            raise SandboxPolicyViolation("command_output_limit_must_be_positive")
        if any("\0" in key or "\0" in value for key, value in self.env.items()):
            raise SandboxPolicyViolation("command_environment_contains_nul")


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    kind: str
    size: int
    modified_at: datetime


@dataclass(frozen=True, slots=True)
class SearchMatch:
    path: str
    line: int
    column: int
    text: str
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    source_sandbox_id: str
    workspace_revision: int
    created_at: datetime
    content_checksum: str
    image_digest: str | None = None


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class StreamEvent(Generic[T]):
    cursor: int
    value: T


@runtime_checkable
class ReplayStream(Protocol[T]):
    async def replay(
        self,
        *,
        after_cursor: int,
    ) -> tuple[StreamEvent[T], ...]: ...

    def subscribe(self, *, after_cursor: int) -> AsyncIterator[StreamEvent[T]]: ...

    async def close(self) -> None: ...


@runtime_checkable
class SandboxSession(Protocol):
    @property
    def sandbox_id(self) -> str: ...

    async def workspace_revision(self) -> int: ...

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]: ...

    async def stat(self, path: str) -> FileEntry: ...

    async def read_file(self, path: str) -> bytes: ...

    async def write_file(self, path: str, content: bytes) -> int: ...

    async def write_file_if_revision(
        self,
        path: str,
        content: bytes,
        *,
        expected_revision: int,
    ) -> int: ...

    async def search_text(
        self,
        query: str,
        *,
        paths: tuple[str, ...] = ("**/*",),
        regex: bool = False,
        limit: int = 100,
        before: int = 0,
        after: int = 0,
    ) -> tuple[SearchMatch, ...]: ...

    async def glob_files(
        self, pattern: str, *, limit: int = 100
    ) -> tuple[str, ...]: ...

    async def git_status(self) -> CommandResult: ...

    async def git_diff(self, *, staged: bool = False) -> CommandResult: ...

    async def git_log(self, *, limit: int = 20) -> CommandResult: ...

    async def execute(self, request: CommandRequest) -> CommandResult: ...

    async def create_pty(self, *, argv: tuple[str, ...]) -> Any: ...

    async def write_pty(self, pty_id: str, data: bytes) -> None: ...

    async def resize_pty(self, pty_id: str, *, rows: int, cols: int) -> None: ...

    async def kill_pty(self, pty_id: str) -> None: ...

    async def watch_files(self, *, after_cursor: int = 0) -> Any: ...


@runtime_checkable
class SandboxProvider(Protocol):
    async def create(
        self,
        *,
        owner_id: str,
        limits: SandboxLimits,
    ) -> Sandbox: ...

    async def get(self, sandbox_id: str) -> Sandbox: ...

    async def suspend(self, sandbox_id: str) -> Sandbox: ...

    async def resume(self, sandbox_id: str) -> Sandbox: ...

    async def snapshot(self, sandbox_id: str) -> Snapshot: ...

    async def restore(self, snapshot_id: str, *, owner_id: str) -> Sandbox: ...

    async def destroy(self, sandbox_id: str) -> None: ...

    async def open_session(self, sandbox_id: str) -> SandboxSession: ...

    async def close(self) -> None: ...
