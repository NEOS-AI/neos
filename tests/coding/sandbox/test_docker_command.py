import asyncio
import os
import signal
import sys

import pytest

from neos.coding.sandbox import command as command_mod
from neos.coding.sandbox import process as process_mod
from neos.coding.sandbox.base import (
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxTimeout,
    SandboxUnavailable,
)
from neos.coding.sandbox.command import (
    DockerCommandResult,
    DockerCommandRunner,
    build_create_args,
)

pytestmark = pytest.mark.no_db


DIGEST_IMAGE = "neos-sandbox@sha256:" + "a" * 64
LIMITS = SandboxLimits.safe_defaults()


def test_create_args_enforce_isolation() -> None:
    args = build_create_args(
        sandbox_id="sb_1",
        image=DIGEST_IMAGE,
        limits=LIMITS,
    )
    joined = " ".join(args)

    assert "--user 10001:10001" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in args
    assert "--network none" in joined
    assert "--pids-limit 128" in joined
    assert "--memory 536870912" in joined
    assert "--cpus 1.0" in joined
    assert "--tmpfs /tmp:rw,noexec,nosuid,size=67108864" in joined
    assert "/var/run/docker.sock" not in joined
    assert "--privileged" not in args


def test_create_args_reject_unpinned_image_by_default() -> None:
    with pytest.raises(SandboxPolicyViolation, match="docker_image_unpinned"):
        build_create_args(
            sandbox_id="sb_1",
            image="neos-sandbox:latest",
            limits=LIMITS,
        )


async def test_runner_maps_timeout_without_leaking_arguments() -> None:
    async def timeout(*args: str, timeout_sec: float):
        raise TimeoutError("registry-token")

    runner = DockerCommandRunner(exec=timeout)

    with pytest.raises(SandboxTimeout) as error:
        await runner.run(
            "login",
            "--password",
            "registry-token",
            timeout_sec=1,
        )

    assert "registry-token" not in str(error.value)


async def test_runner_maps_daemon_failure_without_raw_stderr() -> None:
    async def fail(*args: str, timeout_sec: float):
        return DockerCommandResult(
            exit_code=1,
            stdout=b"",
            stderr=b"daemon registry-token failure",
        )

    runner = DockerCommandRunner(exec=fail)

    with pytest.raises(SandboxUnavailable) as error:
        await runner.run("inspect", "sb_1", timeout_sec=1)

    assert "registry-token" not in str(error.value)


async def test_runner_forwards_bounded_stdin_outside_argv() -> None:
    received = {}

    async def capture(
        *args: str,
        timeout_sec: float,
        input: bytes,
    ) -> DockerCommandResult:
        received["args"] = args
        received["input"] = input
        return DockerCommandResult(exit_code=0, stdout=b"", stderr=b"")

    runner = DockerCommandRunner(exec=capture)
    await runner.run(
        "exec",
        "-i",
        "sb_1",
        "helper",
        timeout_sec=1,
        input=b"file contents",
    )

    assert received == {
        "args": ("exec", "-i", "sb_1", "helper"),
        "input": b"file contents",
    }


_SB = "sb_" + "a" * 32
_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def _create_args(**kwargs):
    return build_create_args(
        sandbox_id=_SB,
        image=_IMAGE,
        limits=SandboxLimits.safe_defaults(),
        **kwargs,
    )


def test_build_create_args_emits_extra_labels() -> None:
    args = _create_args(extra_labels={"com.neos.coding.owner-id": "owner_1"})

    index = args.index("com.neos.coding.owner-id=owner_1")
    assert args[index - 1] == "--label"


def test_build_create_args_is_byte_identical_without_extra_labels() -> None:
    """관리형 라벨이 없을 때 argv가 종전과 완전히 같아야 한다.

    이 단언이 CA5-a 작업이 데이터 플레인을 건드리지 않았다는 증거다.
    """
    assert _create_args(extra_labels=None) == _create_args()
    assert _create_args(extra_labels={}) == _create_args()


def test_build_create_args_rejects_label_injection() -> None:
    with pytest.raises(SandboxPolicyViolation, match="docker_label_invalid"):
        _create_args(extra_labels={"com.neos.coding.owner-id": "a\nb"})


class _FakeStdin:
    def write(self, data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeDockerProcess:
    def __init__(self, *, exit_on: int | None = None, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.stdin = _FakeStdin()
        self.stdout = None
        self.stderr = None
        self._exit_on = exit_on
        self._exited = asyncio.Event()

    async def communicate(self, stdin: bytes | None = None) -> tuple[bytes, bytes]:
        await self._exited.wait()
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


class _ImmediateProcess:
    def __init__(self) -> None:
        self.pid = 7
        self.returncode = 0

    async def wait(self) -> int:
        return 0


async def test_execute_timeout_sigterm_then_sigkill_host_and_guest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDockerProcess(exit_on=signal.SIGKILL)
    sent: list[int] = []
    spawned: list[tuple[str, ...]] = []

    async def create_subprocess_exec(*args: object, **kwargs: object) -> object:
        argv = tuple(str(arg) for arg in args)
        spawned.append(argv)
        if len(argv) > 1 and argv[1] == "kill":
            return _ImmediateProcess()
        assert kwargs.get("start_new_session") is True
        return fake

    def killpg(pid: int, sig: int) -> None:
        if pid == fake.pid:
            sent.append(sig)
            fake.deliver(sig)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.01)
    monkeypatch.setattr(command_mod, "TERMINATE_GRACE_SEC", 0.01)

    runner = DockerCommandRunner()
    with pytest.raises(SandboxTimeout, match="docker_command_timeout"):
        await runner.run(
            "exec",
            "-i",
            "neos-sb_guest",
            "sleep",
            "30",
            timeout_sec=0.01,
        )

    assert sent == [signal.SIGTERM, signal.SIGKILL]
    assert ("docker", "kill", "--signal=TERM", "neos-sb_guest") in spawned
    assert ("docker", "kill", "--signal=KILL", "neos-sb_guest") in spawned


async def test_execute_timeout_sigterm_host_when_guest_id_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDockerProcess(exit_on=signal.SIGKILL)
    sent: list[int] = []
    spawned: list[tuple[str, ...]] = []

    async def create_subprocess_exec(*args: object, **kwargs: object) -> object:
        argv = tuple(str(arg) for arg in args)
        spawned.append(argv)
        if len(argv) > 1 and argv[1] == "kill":
            return _ImmediateProcess()
        return fake

    def killpg(pid: int, sig: int) -> None:
        if pid == fake.pid:
            sent.append(sig)
            fake.deliver(sig)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(process_mod, "TERMINATE_GRACE_SEC", 0.01)
    monkeypatch.setattr(command_mod, "TERMINATE_GRACE_SEC", 0.01)

    runner = DockerCommandRunner()
    with pytest.raises(SandboxTimeout, match="docker_command_timeout"):
        await runner.run("volume", "create", "neos-vol", timeout_sec=0.01)

    assert sent == [signal.SIGTERM, signal.SIGKILL]
    assert all(argv[1] != "kill" for argv in spawned if len(argv) > 1)


async def test_execute_docker_does_not_buffer_via_communicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False
    original = asyncio.subprocess.Process.communicate
    original_create = asyncio.create_subprocess_exec

    async def wrapped(
        self: asyncio.subprocess.Process,
        *args: object,
        **kwargs: object,
    ):
        nonlocal called
        called = True
        return await original(self, *args, **kwargs)

    async def create_subprocess_exec(*args: object, **kwargs: object):
        return await original_create(
            sys.executable,
            "-c",
            "print('ok')",
            **kwargs,
        )

    monkeypatch.setattr(asyncio.subprocess.Process, "communicate", wrapped)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)

    result = await command_mod._execute_docker("version", timeout_sec=2)

    assert called is False
    assert result.exit_code == 0
    assert b"ok" in result.stdout


async def test_execute_docker_truncates_oversized_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_mod, "_DOCKER_MAX_OUTPUT_BYTES", 8, raising=False)
    original_create = asyncio.create_subprocess_exec

    async def create_subprocess_exec(*args: object, **kwargs: object):
        return await original_create(
            sys.executable,
            "-c",
            "import sys; "
            "sys.stdout.buffer.write(b'o' * 20); "
            "sys.stderr.buffer.write(b'e' * 20); "
            "sys.stdout.buffer.flush(); "
            "sys.stderr.buffer.flush()",
            **kwargs,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)

    result = await command_mod._execute_docker("logs", timeout_sec=2)

    assert result.stdout == b"oooooooo"
    assert result.stderr == b"eeeeeeee"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout) == 8
    assert len(result.stderr) == 8


async def test_execute_docker_overflow_does_not_kill_guest_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_mod, "_DOCKER_MAX_OUTPUT_BYTES", 8, raising=False)
    killed: list[tuple[str, str]] = []
    original_create = asyncio.create_subprocess_exec

    async def fake_kill(target: str, sig: str) -> None:
        killed.append((target, sig))

    async def create_subprocess_exec(*args: object, **kwargs: object):
        argv = tuple(str(arg) for arg in args)
        if len(argv) >= 2 and argv[0] == "docker" and argv[1] == "kill":
            raise AssertionError(f"guest kill spawned: {argv}")
        return await original_create(
            sys.executable,
            "-c",
            "import sys, time; "
            "sys.stdout.buffer.write(b'o' * 20); "
            "sys.stdout.buffer.flush(); "
            "time.sleep(2)",
            **kwargs,
        )

    monkeypatch.setattr(command_mod, "_docker_kill_guest", fake_kill)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)

    result = await command_mod._execute_docker(
        "exec", "neos-sb_live", "cat", "huge.txt", timeout_sec=2
    )

    assert result.stdout_truncated is True
    assert killed == []
