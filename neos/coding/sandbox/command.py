from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import pty
import re
import signal
import struct
import termios
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from neos.coding.sandbox.base import (
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxTimeout,
    SandboxUnavailable,
)


_DIGEST_IMAGE = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")
_SANDBOX_ID = re.compile(r"^sb_[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class DockerCommandResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False
    stderr_truncated: bool = False


DockerExec = Callable[..., Awaitable[DockerCommandResult]]


class DockerCommandRunner:
    """The sole sanitized subprocess boundary for Docker CLI access."""

    def __init__(self, *, exec: DockerExec | None = None) -> None:
        self._exec = exec or _execute_docker

    async def run(
        self,
        *args: str,
        timeout_sec: float,
        allowed_exit_codes: tuple[int, ...] = (0,),
        input: bytes = b"",
    ) -> DockerCommandResult:
        if timeout_sec <= 0:
            raise SandboxPolicyViolation("docker_timeout_must_be_positive")
        if any("\0" in arg for arg in args):
            raise SandboxPolicyViolation("docker_argument_contains_nul")
        if len(input) > 16 * 1024 * 1024:
            raise SandboxPolicyViolation("docker_input_limit_exceeded")
        try:
            if input:
                result = await self._exec(
                    *args,
                    timeout_sec=timeout_sec,
                    input=input,
                )
            else:
                result = await self._exec(*args, timeout_sec=timeout_sec)
        except (TimeoutError, asyncio.TimeoutError) as error:
            raise SandboxTimeout("docker_command_timeout") from error
        except FileNotFoundError as error:
            raise SandboxUnavailable("docker_cli_unavailable") from error
        except OSError as error:
            raise SandboxUnavailable("docker_transport_unavailable") from error
        if result.exit_code not in allowed_exit_codes:
            raise SandboxUnavailable(
                f"docker_command_failed:{result.exit_code}"
            )
        return result


class DockerInteractiveProcess:
    """Interactive Docker CLI process attached to a local POSIX PTY."""

    def __init__(self, process: asyncio.subprocess.Process, master_fd: int) -> None:
        self._process = process
        self._master_fd = master_fd

    @classmethod
    async def start(cls, *args: str) -> DockerInteractiveProcess:
        if any("\0" in arg for arg in args):
            raise SandboxPolicyViolation("docker_argument_contains_nul")
        master_fd, slave_fd = pty.openpty()
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                *args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        except (FileNotFoundError, OSError) as error:
            os.close(master_fd)
            raise SandboxUnavailable("docker_cli_unavailable") from error
        finally:
            os.close(slave_fd)
        return cls(process, master_fd)

    async def read(self, maximum: int) -> bytes:
        loop = asyncio.get_running_loop()
        ready = loop.create_future()

        def read_ready() -> None:
            if ready.done():
                return
            try:
                ready.set_result(os.read(self._master_fd, maximum))
            except OSError as error:
                if error.errno == errno.EIO:
                    ready.set_result(b"")
                else:
                    ready.set_exception(error)

        loop.add_reader(self._master_fd, read_ready)
        try:
            return await ready
        finally:
            loop.remove_reader(self._master_fd)

    async def write(self, data: bytes) -> None:
        await asyncio.to_thread(os.write, self._master_fd, data)

    async def resize(self, *, rows: int, cols: int) -> None:
        fcntl.ioctl(
            self._master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    async def terminate(self) -> None:
        if self._process.returncode is None:
            try:
                os.killpg(self._process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def wait(self) -> int:
        code = await self._process.wait()
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        return code


_LABEL_VALUE_FORBIDDEN = ("\n", "\r", "\x00")


def _label_args(labels: Mapping[str, str] | None) -> tuple[str, ...]:
    """관리형 라벨을 `--label key=value` 쌍으로 렌더링한다.

    개행·NUL이 섞이면 argv 인젝션으로 이어질 수 있어 여기서 차단한다.
    """
    if not labels:
        return ()
    rendered: list[str] = []
    for key, value in labels.items():
        text = f"{key}={value}"
        if any(bad in text for bad in _LABEL_VALUE_FORBIDDEN):
            raise SandboxPolicyViolation("docker_label_invalid")
        rendered.extend(("--label", text))
    return tuple(rendered)


def build_create_args(
    *,
    sandbox_id: str,
    image: str,
    limits: SandboxLimits,
    network_mode: str = "none",
    allow_unpinned_image: bool = False,
    tmpfs_bytes: int = 64 * 1024 * 1024,
    extra_labels: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    if not _SANDBOX_ID.fullmatch(sandbox_id):
        raise SandboxPolicyViolation("sandbox_id_invalid")
    if not allow_unpinned_image and not _DIGEST_IMAGE.fullmatch(image):
        raise SandboxPolicyViolation("docker_image_unpinned")
    if network_mode != "none":
        raise SandboxPolicyViolation("docker_network_not_isolated")
    if tmpfs_bytes < 1:
        raise SandboxPolicyViolation("docker_tmpfs_limit_invalid")

    volume = f"neos-sandbox-{sandbox_id}"
    return (
        "create",
        "--name",
        f"neos-{sandbox_id}",
        "--label",
        "com.neos.coding.sandbox=true",
        "--label",
        f"com.neos.coding.sandbox-id={sandbox_id}",
        *_label_args(extra_labels),
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--network",
        network_mode,
        "--pids-limit",
        str(limits.pids),
        "--memory",
        str(limits.memory_bytes),
        "--cpus",
        str(limits.cpu_count),
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,size={tmpfs_bytes}",
        "--mount",
        f"type=volume,source={volume},target=/workspace",
        "--workdir",
        "/workspace",
        image,
        "sleep",
        "infinity",
    )


async def _execute_docker(
    *args: str,
    timeout_sec: float,
    input: bytes = b"",
) -> DockerCommandResult:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=(
            asyncio.subprocess.PIPE
            if input
            else asyncio.subprocess.DEVNULL
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(timeout_sec):
            stdout, stderr = await process.communicate(input or None)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    maximum = 1024 * 1024
    return DockerCommandResult(
        exit_code=process.returncode,
        stdout=stdout[:maximum],
        stderr=stderr[:maximum],
        stdout_truncated=len(stdout) > maximum,
        stderr_truncated=len(stderr) > maximum,
    )
