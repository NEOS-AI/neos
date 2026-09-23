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
from neos.coding.sandbox.process import (
    TERMINATE_GRACE_SEC,
    _close_stdio,
    _feed_stdin,
    _read_capped,
    _read_task_result,
    _signal_process_group,
    terminate_process_group,
)


_DIGEST_IMAGE = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")
_SANDBOX_ID = re.compile(r"^sb_[A-Za-z0-9_-]+$")
_DOCKER_MAX_OUTPUT_BYTES = 1024 * 1024


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

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        master_fd: int,
        guest: str | None = None,
    ) -> None:
        self._process = process
        self._master_fd = master_fd
        self._guest = guest

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
        return cls(process, master_fd, _docker_guest_id(args))

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
        # Interactive `docker exec` targets the long-lived sandbox
        # container name. Kill only the CLI process group — same as
        # stream overflow. `_terminate_docker_process` is for timeout
        # of a container the CLI actually owns (`docker run`).
        await terminate_process_group(self._process)

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
    evidence_volume: str | None = None,
) -> tuple[str, ...]:
    if not _SANDBOX_ID.fullmatch(sandbox_id):
        raise SandboxPolicyViolation("sandbox_id_invalid")
    if not allow_unpinned_image and not _DIGEST_IMAGE.fullmatch(image):
        raise SandboxPolicyViolation("docker_image_unpinned")
    if network_mode != "none":
        raise SandboxPolicyViolation("docker_network_not_isolated")
    if tmpfs_bytes < 1:
        raise SandboxPolicyViolation("docker_tmpfs_limit_invalid")
    if evidence_volume is not None and evidence_volume != evidence_volume_name(
        sandbox_id
    ):
        raise SandboxPolicyViolation("docker_evidence_volume_invalid")

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
        *_evidence_mount_args(evidence_volume),
        "--workdir",
        "/workspace",
        image,
        "sleep",
        "infinity",
    )


#: 계약 §3.1 의 경로. 워커 컨테이너에서는 **읽기 전용**으로만 붙는다.
EVIDENCE_MOUNT = "/evidence"
#: 같은 볼륨의 두 번째 읽기 전용 자리. 세션 도구(`read_file.v1` 등)는
#: 워크스페이스 상대 경로만 받으므로(`normalize_workspace_path`), 이 자리가
#: 없으면 워커는 증거를 스크립트로만 읽을 수 있다.
EVIDENCE_WORKSPACE_MOUNT = "/workspace/evidence"


def evidence_volume_name(sandbox_id: str) -> str:
    if not _SANDBOX_ID.fullmatch(sandbox_id):
        raise SandboxPolicyViolation("sandbox_id_invalid")
    return f"neos-evidence-{sandbox_id}"


def _evidence_mount_args(evidence_volume: str | None) -> tuple[str, ...]:
    """증거 볼륨을 워커 컨테이너에 **읽기 전용으로만** 붙인다.

    `volume-nocopy` 는 이미지가 그 자리에 미리 넣어 둔 파일이 빈 볼륨으로
    복사되는 것을 막는다 -- 복사를 허용하면 이미지가 원장에 없는 "증거"를
    심을 수 있고, 볼륨 루트의 소유자도 이미지가 정하게 된다.
    """
    if evidence_volume is None:
        return ()
    return tuple(
        arg
        for target in (EVIDENCE_MOUNT, EVIDENCE_WORKSPACE_MOUNT)
        for arg in (
            "--mount",
            f"type=volume,source={evidence_volume},target={target},"
            "readonly,volume-nocopy",
        )
    )


def build_evidence_writer_args(
    *,
    sandbox_id: str,
    image: str,
    writer_id: str,
    helper: str,
    name: str,
    memory_bytes: int,
    allow_unpinned_image: bool = False,
    extra_labels: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """증거 볼륨에 쓰는 **유일한** 컨테이너. 한 번 쓰고 사라진다(`--rm`).

    워커 컨테이너에는 증거 볼륨의 쓰기 가능한 자리가 하나도 없다. 쓰기는
    오케스트레이터가 부르는 이 짧은 컨테이너에서만 일어난다. `--user 0:0`
    인 이유는 볼륨 루트가 root 소유(0755)이기 때문이고, `--cap-drop ALL`
    이므로 root 는 소유자 권한 말고는 아무것도 갖지 않는다(DAC_OVERRIDE ·
    CHOWN 없음). 네트워크는 없다.
    """
    if not _SANDBOX_ID.fullmatch(sandbox_id):
        raise SandboxPolicyViolation("sandbox_id_invalid")
    if not allow_unpinned_image and not _DIGEST_IMAGE.fullmatch(image):
        raise SandboxPolicyViolation("docker_image_unpinned")
    if not _EVIDENCE_WRITER_ID.fullmatch(writer_id):
        raise SandboxPolicyViolation("docker_evidence_writer_id_invalid")
    if not _EVIDENCE_NAME.fullmatch(name):
        raise SandboxPolicyViolation("evidence_name_invalid")
    if memory_bytes < 1:
        raise SandboxPolicyViolation("docker_memory_limit_invalid")
    return (
        "run",
        "--rm",
        "-i",
        "--name",
        f"neos-{sandbox_id}-evidence-{writer_id}",
        "--label",
        "com.neos.coding.evidence-writer=true",
        "--label",
        f"com.neos.coding.sandbox-id={sandbox_id}",
        *_label_args(extra_labels),
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--network",
        "none",
        "--pids-limit",
        "16",
        "--memory",
        str(memory_bytes),
        "--mount",
        f"type=volume,source={evidence_volume_name(sandbox_id)},"
        f"target={EVIDENCE_MOUNT},volume-nocopy",
        image,
        "python",
        "-c",
        helper,
        name,
    )


_EVIDENCE_WRITER_ID = re.compile(r"^[0-9a-f]{8,32}$")
#: 원장의 raw_ref 는 16자 hex 다. 이름은 그보다 넓게 받되 경로 구분자·점으로
#: 시작하는 이름(임시 파일 자리)은 받지 않는다.
_EVIDENCE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}\.txt$")


_DOCKER_VALUE_OPTS = {
    "-e",
    "--env",
    "-u",
    "--user",
    "-w",
    "--workdir",
    "-s",
    "--signal",
    "--env-file",
    "--name",
    "--network",
    "--label",
    "--memory",
    "--cpus",
    "--pids-limit",
    "--security-opt",
    "--tmpfs",
    "--mount",
    "--cidfile",
    "--time",
    "-t",
}

_DOCKER_GUEST_COMMANDS = {
    "exec",
    "run",
    "start",
    "stop",
    "kill",
    "rm",
    "inspect",
    "attach",
    "logs",
    "wait",
    "restart",
    "pause",
    "unpause",
}


def _docker_option_value(args: tuple[str, ...], option: str) -> str | None:
    prefix = f"{option}="
    for index, arg in enumerate(args):
        if arg == option and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


def _docker_guest_id(args: tuple[str, ...]) -> str | None:
    if not args:
        return None
    named = _docker_option_value(args, "--name")
    if named and "\0" not in named and not named.startswith("-"):
        return named
    if args[0] not in _DOCKER_GUEST_COMMANDS:
        return None
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--":
            if index + 1 >= len(args):
                return None
            target = args[index + 1]
            return target if target and "\0" not in target else None
        if arg.startswith("-"):
            key, separator, _value = arg.partition("=")
            # `docker exec/run -t` is --tty. `-t` is --time only on
            # stop/restart/rm.
            takes_value = key in _DOCKER_VALUE_OPTS and not (
                key == "-t" and args[0] in {"exec", "run", "create"}
            )
            if separator or not takes_value:
                index += 1
                continue
            index += 2
            continue
        if "\0" in arg or arg.startswith("-"):
            return None
        return arg
    return None


async def _docker_kill_guest(target: str, sig: str) -> None:
    if not target or "\0" in target or target.startswith("-"):
        return
    try:
        killer = await asyncio.create_subprocess_exec(
            "docker",
            "kill",
            f"--signal={sig}",
            target,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError):
        return
    try:
        async with asyncio.timeout(2.0):
            await killer.wait()
    except TimeoutError:
        if killer.pid is not None:
            _signal_process_group(killer.pid, signal.SIGKILL)
        await killer.wait()


async def _terminate_docker_process(
    process: asyncio.subprocess.Process,
    guest: str | None,
) -> None:
    if guest is None:
        await terminate_process_group(process)
        return
    if process.returncode is None and process.pid is not None:
        _signal_process_group(process.pid, signal.SIGTERM)
    await _docker_kill_guest(guest, "TERM")
    if process.returncode is not None:
        return
    try:
        async with asyncio.timeout(TERMINATE_GRACE_SEC):
            await process.wait()
    except TimeoutError:
        if process.returncode is None and process.pid is not None:
            _signal_process_group(process.pid, signal.SIGKILL)
        _close_stdio(process)
        await _docker_kill_guest(guest, "KILL")
        if process.returncode is None:
            await process.wait()


async def _collect_docker(
    process: asyncio.subprocess.Process,
    input: bytes,
) -> tuple[bytes, bytes, bool, bool]:
    overflow = asyncio.Event()
    stdin_task = asyncio.create_task(_feed_stdin(process, input))
    stdout_task = asyncio.create_task(
        _read_capped(process.stdout, _DOCKER_MAX_OUTPUT_BYTES, overflow)
    )
    stderr_task = asyncio.create_task(
        _read_capped(process.stderr, _DOCKER_MAX_OUTPUT_BYTES, overflow)
    )
    wait_task = asyncio.create_task(process.wait())
    overflow_task = asyncio.create_task(overflow.wait())
    try:
        await asyncio.wait(
            {wait_task, overflow_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if overflow.is_set():
            for task in (stdout_task, stderr_task, wait_task):
                if not task.done():
                    task.cancel()
            if process.returncode is None:
                # Cap the exec stream only. Do not docker-kill the
                # long-lived sandbox container (guest id is the
                # `docker exec` target name).
                await terminate_process_group(process)
        elif not wait_task.done():
            await wait_task
        stdout, stdout_truncated = await _read_task_result(stdout_task)
        stderr, stderr_truncated = await _read_task_result(stderr_task)
        await stdin_task
    finally:
        overflow_task.cancel()
        for task in (stdin_task, stdout_task, stderr_task, wait_task):
            if not task.done():
                task.cancel()
    return stdout, stderr, stdout_truncated, stderr_truncated


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
            stdout, stderr, stdout_truncated, stderr_truncated = (
                await _collect_docker(process, input)
            )
    except TimeoutError:
        await _terminate_docker_process(process, _docker_guest_id(args))
        raise
    return DockerCommandResult(
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )
