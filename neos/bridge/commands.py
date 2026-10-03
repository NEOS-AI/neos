"""브리지의 명령 실행 -- 트랙 Q16c. **이 파일만** 프로세스를 띄운다.

사용자가 `--allow-commands EXE,...` 로 이름을 댄 실행 파일만 돈다. 나머지 브리지 모듈은 여전히
아무것도 실행하지 않고(소스 스캔 테스트가 고정한다), 이 모듈은 `__main__` 이 그 플래그를 받았을
때만 import 한다.

경계(BC7 · BC8):

- argv 규칙은 서버와 **같은 함수**(`device_command_refusal`) -- 셸·래퍼·권한 상승·런처 거절,
  허용 목록, 인라인 코드, 루트 밖·비밀 경로 피연산자
- 실행 파일 경로는 **시작할 때** `PATH` 에서 찾아 고정한다. 루트 폴더 안에 있으면 거절한다 --
  브리지의 쓰기(Q16b)로 바꿔치기할 수 있는 자리에 있는 것을 돌리지 않는다
- 셸 없이(`shell=False`) argv 그대로. stdin 은 비어 있다. 환경은 허용한 몇 개만 넘긴다 --
  브리지 토큰(`NEOS_BRIDGE_TOKEN`)도 셸의 다른 비밀도 자식에게 가지 않는다
- cwd 는 루트 기준 상대 경로, 실경로로 다시 봐서 루트 안의 디렉터리
- 새 세션(프로세스 그룹)으로 띄우고, 시간이 넘으면 그룹째 SIGKILL, 끝난 뒤에도 그룹을 정리한다
- stdout·stderr 각각 상한까지만 모으고 나머지는 읽어 버린다(파이프가 막혀 멈추지 않게)
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from neos.bridge.tools import BridgeToolError, LocalReadOnlyTools
from neos.coding.bridge.command_policy import device_command_refusal, executable_name_refusal

COMMAND_RISK = "command"
COMMAND_TOOL_NAMES = ("run_command",)
#: 자식 프로세스에 넘기는 환경변수. 이것 말고는 아무것도 넘기지 않는다.
PASSED_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "USER", "LOGNAME")
_FIXED_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_READ_CHUNK = 65_536


def _resolve_executable(name: str, root: Path) -> str:
    """이름 -> 고정한 실경로. 없거나 루트 안이면 ValueError."""
    if executable_name_refusal(name) is not None:
        raise ValueError(f"{name!r} cannot be allowed on a device (shell, wrapper or launcher)")
    found = shutil.which(name)
    if found is None:
        raise ValueError(f"{name!r} is not on PATH")
    real = Path(os.path.realpath(found))
    if real == root or root in real.parents:
        raise ValueError(f"{name!r} lives inside the shared folder; refusing to run it")
    return str(real)


def _child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in PASSED_ENV if key in os.environ}
    env.update(_FIXED_ENV)
    return env


class _CappedReader(threading.Thread):
    def __init__(self, stream: Any, cap: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._cap = cap
        self.data = bytearray()
        self.cut = False

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(_READ_CHUNK)
                if not chunk:
                    return
                room = self._cap - len(self.data)
                if room > 0:
                    self.data.extend(chunk[:room])
                if len(chunk) > max(room, 0):
                    self.cut = True  # 넘는 것은 읽어 버린다
        except (OSError, ValueError):
            return


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class CommandRunner:
    """`run_command` 하나. 기반 도구(읽기 또는 읽기+쓰기)의 루트·경로 규칙을 그대로 쓴다."""

    def __init__(
        self,
        base: LocalReadOnlyTools,
        executables: Iterable[str],
        *,
        max_output_bytes: int = 65_536,
        max_timeout_sec: float = 60.0,
    ) -> None:
        if os.name != "posix" or not hasattr(os, "killpg"):
            raise ValueError("device commands need a POSIX system (process groups)")
        names = tuple(dict.fromkeys(executables))
        if not names:
            raise ValueError("--allow-commands needs at least one executable name")
        if max_output_bytes < 1 or max_timeout_sec <= 0:
            raise ValueError("limits must be positive")
        self.base = base
        self.root = base.root
        self._paths = {name: _resolve_executable(name, base.root) for name in names}
        self._max_output = max_output_bytes
        self._max_timeout = max_timeout_sec

    @property
    def executables(self) -> frozenset[str]:
        return frozenset(self._paths)

    def declaration(self) -> list[dict[str, Any]]:
        commands = [
            {"name": name, "risk": COMMAND_RISK, "executables": sorted(self._paths)}
            for name in COMMAND_TOOL_NAMES
        ]
        return self.base.declaration() + commands

    def call(self, tool: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if tool == "run_command":
            return self.run_command(
                args.get("argv"),
                cwd=args.get("cwd", "."),
                timeout_sec=args.get("timeout_sec"),
                max_output_bytes=args.get("max_output_bytes"),
            )
        return self.base.call(tool, args)

    def _limit(self, requested: object, ceiling: float) -> float:
        if isinstance(requested, (int, float)) and not isinstance(requested, bool) and requested > 0:
            return min(float(requested), ceiling)
        return ceiling

    def run_command(
        self,
        argv: object,
        *,
        cwd: object = ".",
        timeout_sec: object = None,
        max_output_bytes: object = None,
    ) -> dict[str, Any]:
        refusal = device_command_refusal(argv, self._paths)
        if refusal is not None:
            raise BridgeToolError(refusal)
        assert isinstance(argv, (list, tuple))
        _relative, real_cwd = self.base.resolve(cwd if cwd is not None else ".")
        if not real_cwd.is_dir():
            raise BridgeToolError("not_a_directory")
        timeout = self._limit(timeout_sec, self._max_timeout)
        cap = int(self._limit(max_output_bytes, float(self._max_output)))
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(argv),
                executable=self._paths[argv[0]],
                cwd=str(real_cwd),
                env=_child_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as error:
            raise BridgeToolError("command_failed_to_start") from error
        readers = [_CappedReader(process.stdout, cap), _CappedReader(process.stderr, cap)]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(process.pid)
            process.wait()
        finally:
            # 끝난 뒤에도 그룹에 남은 백그라운드 자식을 정리한다.
            _kill_group(process.pid)
        for reader in readers:
            reader.join(timeout=5)
        stdout, stderr = readers
        return {
            "exit_code": None if timed_out else process.returncode,
            "timed_out": timed_out,
            "stdout": bytes(stdout.data).decode("utf-8", errors="replace"),
            "stderr": bytes(stderr.data).decode("utf-8", errors="replace"),
            "truncated": stdout.cut or stderr.cut,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


__all__ = ["COMMAND_RISK", "COMMAND_TOOL_NAMES", "CommandRunner", "PASSED_ENV"]
