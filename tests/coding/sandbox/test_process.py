import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from neos.coding.sandbox import process as process_mod
from neos.coding.sandbox.base import CommandRequest

pytestmark = pytest.mark.no_db
from neos.coding.sandbox.process import BoundedProcessRunner


class _FakeProcess:
    def __init__(self, *, exit_on: int | None = None) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self._exit_on = exit_on
        self._exited = asyncio.Event()

    async def communicate(self, stdin: bytes = b"") -> tuple[bytes, bytes]:
        await asyncio.sleep(30)
        return b"", b""

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def deliver(self, sig: int) -> None:
        if self.returncode is not None:
            return
        if self._exit_on is None or sig == self._exit_on:
            self.returncode = -sig
            self._exited.set()


async def test_process_timeout_kills_child_group(tmp_path: Path) -> None:
    result = await BoundedProcessRunner().run(
        CommandRequest(
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(5)",
            ),
            timeout_sec=0.05,
        ),
        cwd=tmp_path,
        env={},
    )

    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stdout == b""
    assert result.stderr == b""


async def test_timeout_sends_sigterm_then_sigkill_when_still_alive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeProcess(exit_on=signal.SIGKILL)
    sent: list[int] = []

    async def create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        assert kwargs.get("start_new_session") is True
        return fake

    def killpg(pid: int, sig: int) -> None:
        assert pid == fake.pid
        sent.append(sig)
        fake.deliver(sig)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.01)

    result = await BoundedProcessRunner().run(
        CommandRequest(argv=(sys.executable, "-c", "pass"), timeout_sec=0.01),
        cwd=tmp_path,
        env={},
    )

    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stdout == b""
    assert result.stderr == b""
    assert sent == [signal.SIGTERM, signal.SIGKILL]


async def test_timeout_skips_sigkill_when_process_exits_on_sigterm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeProcess(exit_on=signal.SIGTERM)
    sent: list[int] = []

    async def create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return fake

    def killpg(pid: int, sig: int) -> None:
        sent.append(sig)
        fake.deliver(sig)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.01)

    result = await BoundedProcessRunner().run(
        CommandRequest(argv=(sys.executable, "-c", "pass"), timeout_sec=0.01),
        cwd=tmp_path,
        env={},
    )

    assert result.timed_out is True
    assert result.exit_code is None
    assert sent == [signal.SIGTERM]


async def test_process_truncates_stdout_and_stderr_independently(
    tmp_path: Path,
) -> None:
    result = await BoundedProcessRunner().run(
        CommandRequest(
            argv=(
                sys.executable,
                "-c",
                "import sys; print('o' * 20); print('e' * 20, file=sys.stderr)",
            ),
            timeout_sec=2,
            max_output_bytes=8,
        ),
        cwd=tmp_path,
        env={},
    )

    assert result.exit_code == 0
    assert result.stdout == b"oooooooo"
    assert result.stderr == b"eeeeeeee"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
