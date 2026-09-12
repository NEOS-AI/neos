import asyncio
import os
import pty
import signal
import sys
from pathlib import Path

import pytest

from neos.coding.sandbox import process as process_mod
from neos.coding.sandbox.base import CommandRequest
from neos.coding.sandbox.command import DockerInteractiveProcess
from neos.coding.sandbox.events import PtyOutput
from neos.coding.sandbox.memory import MemoryPty
from neos.coding.sandbox.process import BoundedProcessRunner

pytestmark = pytest.mark.no_db


class _FakeStream:
    def __init__(self, *, hang: bool = True, payload: bytes = b"") -> None:
        self._hang = hang
        self._payload = payload

    async def read(self, n: int = -1) -> bytes:
        if self._hang:
            await asyncio.Event().wait()
            return b""
        if not self._payload:
            return b""
        if n < 0:
            data, self._payload = self._payload, b""
            return data
        data, self._payload = self._payload[:n], self._payload[n:]
        return data


class _FakeStdin:
    def write(self, data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, *, exit_on: int | None = None) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.stdin = _FakeStdin()
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()
        self._exit_on = exit_on
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def deliver(self, sig: int) -> None:
        if self.returncode is not None:
            return
        if self._exit_on is None or sig == self._exit_on:
            self.returncode = -sig
            self.stdout._hang = False
            self.stderr._hang = False
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
                "import sys; "
                "sys.stdout.buffer.write(b'o' * 20); "
                "sys.stderr.buffer.write(b'e' * 20); "
                "sys.stdout.buffer.flush(); "
                "sys.stderr.buffer.flush()",
            ),
            timeout_sec=2,
            max_output_bytes=8,
        ),
        cwd=tmp_path,
        env={},
    )

    assert result.stdout == b"oooooooo"
    assert result.stderr == b"eeeeeeee"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


async def test_process_does_not_buffer_via_communicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False
    original = asyncio.subprocess.Process.communicate

    async def wrapped(self: asyncio.subprocess.Process, *args: object, **kwargs: object):
        nonlocal called
        called = True
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(asyncio.subprocess.Process, "communicate", wrapped)
    result = await BoundedProcessRunner().run(
        CommandRequest(
            argv=(sys.executable, "-c", "print('ok')"),
            timeout_sec=2,
            max_output_bytes=16,
        ),
        cwd=tmp_path,
        env={},
    )

    assert called is False
    assert result.timed_out is False
    assert b"ok" in result.stdout


async def test_output_cap_kills_flooder_without_unbounded_buffer(
    tmp_path: Path,
) -> None:
    result = await BoundedProcessRunner().run(
        CommandRequest(
            argv=(
                sys.executable,
                "-u",
                "-c",
                "import sys\n"
                "chunk = b'x' * 4096\n"
                "while True:\n"
                "    sys.stdout.buffer.write(chunk)\n"
                "    sys.stdout.buffer.flush()\n",
            ),
            timeout_sec=5,
            max_output_bytes=64,
        ),
        cwd=tmp_path,
        env={},
    )

    assert result.timed_out is False
    assert result.stdout == b"x" * 64
    assert result.stdout_truncated is True
    assert len(result.stdout) == 64


def _ignore_sigterm_script() -> str:
    return (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.write('ready\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )


async def test_docker_pty_terminate_sends_sigterm_then_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeProcess(exit_on=signal.SIGKILL)
    sent: list[int] = []

    def killpg(pid: int, sig: int) -> None:
        assert pid == fake.pid
        sent.append(sig)
        fake.deliver(sig)

    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.01)

    await DockerInteractiveProcess(fake, -1).terminate()

    assert sent == [signal.SIGTERM, signal.SIGKILL]


async def test_docker_pty_terminate_skips_sigkill_after_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeProcess(exit_on=signal.SIGTERM)
    sent: list[int] = []

    def killpg(pid: int, sig: int) -> None:
        sent.append(sig)
        fake.deliver(sig)

    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.01)

    await DockerInteractiveProcess(fake, -1).terminate()

    assert sent == [signal.SIGTERM]


async def test_memory_pty_terminate_sends_sigterm_then_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.05)
    master_fd, slave_fd = pty.openpty()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ignore_sigterm_script(),
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True,
    )
    os.close(slave_fd)
    sent: list[int] = []
    real_killpg = os.killpg

    def killpg(pid: int, sig: int) -> None:
        sent.append(sig)
        real_killpg(pid, sig)

    monkeypatch.setattr(os, "killpg", killpg)
    terminal = MemoryPty(
        pty_id="pty_term",
        process=process,
        master_fd=master_fd,
        replay_events=8,
        replay_bytes=256,
    )
    async with asyncio.timeout(2):
        async for event in terminal.subscribe(after_cursor=0):
            if isinstance(event.value, PtyOutput) and b"ready" in event.value.data:
                break

    closed = await terminal.terminate("pty_killed")

    assert sent == [signal.SIGTERM, signal.SIGKILL]
    assert process.returncode is not None
    assert closed.reason == "pty_killed"
