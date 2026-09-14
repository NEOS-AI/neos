"""Helper-script session over a remote exec transport.

Managed providers (E2B, Modal, ...) expose "run this argv in that sandbox".
That is enough for the shared helper-script session: every file, search, and
git operation becomes one exec. Vendor SDKs never appear here -- a transport
implements the narrow `SandboxExecTransport` protocol and is injected.

PTYs are refused (`pty_unsupported`) rather than emulated: a terminal that
silently drops input is worse than no terminal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from neos.coding.sandbox.base import (
    CommandRequest,
    Sandbox,
    SandboxNotFound,
    SandboxTimeout,
    SandboxUnavailable,
)
from neos.coding.sandbox.events import SandboxWatcherHub
from neos.coding.sandbox.helper_session import HelperScriptSandboxSession


@dataclass(frozen=True, slots=True)
class ExecResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


@runtime_checkable
class SandboxExecTransport(Protocol):
    """Runs one argv inside one provider sandbox. Never through a shell.

    A non-zero exit is a result, not an exception. Transport failures
    (network, auth, missing sandbox) raise `SandboxUnavailable`.
    """

    @property
    def name(self) -> str: ...

    async def exec(
        self,
        argv: Sequence[str],
        *,
        workdir: str,
        env: Mapping[str, str],
        stdin: bytes,
        timeout_sec: float,
    ) -> ExecResult: ...


@dataclass(slots=True)
class RemoteSessionRecord:
    sandbox: Sandbox
    watcher: SandboxWatcherHub
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    known_paths: set[str] = field(default_factory=set)
    watching: bool = False


class RemoteSandboxSession(HelperScriptSandboxSession):
    _INVALID_OUTPUT = "remote_helper_output_invalid"

    def __init__(
        self,
        *,
        record: RemoteSessionRecord,
        transport: SandboxExecTransport,
        allowed_env_names: frozenset[str],
        operation_timeout_sec: float,
        ensure_running: Callable[[str], Awaitable[None]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(record)
        self._transport = transport
        self._allowed = allowed_env_names
        self._operation_timeout_sec = operation_timeout_sec
        self._ensure_running_hook = ensure_running
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _ensure_running(self) -> None:
        await self._ensure_running_hook(self.sandbox_id)

    @property
    def _allowed_env_names(self) -> frozenset[str]:
        return self._allowed

    def _now(self) -> datetime:
        return self._clock()

    async def _run_helper(
        self,
        helper: str,
        *args: str,
        input: bytes = b"",
    ) -> ExecResult:
        await self._ensure_running()
        result = await self._transport.exec(
            ("python", "-c", helper, *args),
            workdir="/workspace",
            env={},
            stdin=input,
            timeout_sec=self._operation_timeout_sec,
        )
        self._raise_if_timed_out(result)
        if result.exit_code != 0:
            raise SandboxUnavailable(
                f"{self._transport.name}_command_failed:{result.exit_code}"
            )
        return result

    async def _run_command(
        self,
        request: CommandRequest,
        *,
        workdir: str,
        env: Mapping[str, str],
        timeout_sec: float,
    ) -> ExecResult:
        result = await self._transport.exec(
            tuple(request.argv),
            workdir=workdir,
            env=dict(env),
            stdin=request.stdin,
            timeout_sec=timeout_sec,
        )
        self._raise_if_timed_out(result)
        return result

    def _raise_if_timed_out(self, result: ExecResult) -> None:
        if result.timed_out:
            raise SandboxTimeout(f"{self._transport.name}_command_timeout")

    async def create_pty(self, *, argv: tuple[str, ...]):
        raise SandboxUnavailable("pty_unsupported")

    async def write_pty(self, pty_id: str, data: bytes) -> None:
        raise SandboxNotFound(pty_id)

    async def resize_pty(self, pty_id: str, *, rows: int, cols: int) -> None:
        raise SandboxNotFound(pty_id)

    async def kill_pty(self, pty_id: str) -> None:
        raise SandboxNotFound(pty_id)
