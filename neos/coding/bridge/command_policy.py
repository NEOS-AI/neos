"""기기 명령의 argv 규칙 -- 트랙 Q16c (BC4 · BC5).

서버 검증기(`catalog.check_device_input`)와 참조 클라이언트(`neos.bridge.commands`)가 **이 함수 하나**를
쓴다 -- `write_policy.device_write_refusal` 과 같은 이유(사본이 둘이면 한쪽만 새 이름을 안다).
무거운 import 가 없어야 한다: 클라이언트는 사용자 기기에서 돈다.

서버는 여기에 더해 샌드박스 `execute.v1` 의 argv 규칙(`registry.validate_argv`)을 같은 argv 에
건다 -- 기기 쪽은 그보다 좁기만 하다.

막는 것: 맨 이름이 아닌 실행 파일 · 허용 목록 밖 · 셸·래퍼·권한 상승·런처·네트워크 클라이언트(허용
목록에 적혀 있어도) · 인라인 인터프리터 코드 · 루트 밖 피연산자(절대·`~`·`..`, `--opt=값` 의 값도) ·
비밀 경로 피연산자 · `secret://` · NUL · 크기.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: argv 의 모양 상한. 스키마(`catalog._DeviceCommandInput`)와 같은 값이다.
MAX_ARGV_ITEMS = 64
MAX_ARGV_ITEM_CHARS = 4096
MAX_ARGV_TOTAL_CHARS = 32_768
#: 클라이언트가 선언할 수 있는 실행 파일 수.
MAX_DECLARED_EXECUTABLES = 32

EXECUTABLE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

#: 허용 목록에 **적혀 있어도** 기기에서 돌지 않는 실행 파일. 설정 검증 · 클라이언트 시작 ·
#: 선언 검사 · 검증기가 이 목록 하나를 본다.
NEVER_ON_DEVICE: frozenset[str] = frozenset(
    {
        # 셸 -- argv 를 다시 문자열로 만드는 길
        "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish", "ash", "busybox",
        "pwsh", "powershell", "cmd", "cmd.exe", "powershell.exe",
        # 래퍼 -- 허용 목록을 다른 실행 파일로 넘는 길
        "env", "xargs", "timeout", "nice", "nohup", "time", "stdbuf", "command", "exec",
        "setsid", "script", "watch", "parallel", "find", "npx", "dlx",
        # 권한 상승
        "sudo", "su", "doas", "pkexec", "runas",
        # 런처 · 자동 실행 · 예약
        "open", "xdg-open", "start", "osascript", "launchctl", "systemctl", "crontab", "at",
        "schtasks", "rundll32", "regsvr32", "mshta", "wscript", "cscript",
        # 네트워크 클라이언트(샌드박스 규칙과 같다 -- 클라이언트 쪽에서도 막는다)
        "curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "telnet", "ftp",
    }
)

#: 인라인 코드를 받는 인터프리터. 이것들의 `-c`/`-e`/`-p`/`--eval`·`-r`(php) 은 거절한다.
_INLINE_INTERPRETERS = frozenset(
    {"python", "python3", "node", "nodejs", "perl", "ruby", "php", "lua", "deno", "bun"}
)
_SECRET_REF_MARK = "secret://"


def executable_name_refusal(name: object) -> str | None:
    """허용 목록에 둘 수 없는 이름이면 이유, 둘 수 있으면 `None`."""
    if not isinstance(name, str) or not EXECUTABLE_NAME_RE.fullmatch(name):
        return "command_refused"
    if name.casefold() in NEVER_ON_DEVICE:
        return "command_refused"
    return None


def parse_executables(raw: object) -> frozenset[str] | None:
    """선언된 실행 파일 목록 -> 집합. 하나라도 어긋나면 `None`(부분 수락은 없다)."""
    if not isinstance(raw, (list, tuple)) or not raw or len(raw) > MAX_DECLARED_EXECUTABLES:
        return None
    if any(executable_name_refusal(name) is not None for name in raw):
        return None
    names = frozenset(raw)
    return names if len(names) == len(raw) else None


def _escapes(value: str) -> bool:
    text = value.replace("\\", "/")
    if text.startswith("/") or text.startswith("~") or re.match(r"^[A-Za-z]:", text):
        return True
    return ".." in [part for part in text.split("/") if part not in {"", "."}]


def _operand_values(argv: tuple[str, ...]) -> Iterable[str]:
    """피연산자와 `--opt=값` 의 값. 플래그 뒤에 따로 붙은 값은 피연산자로 읽는다(좁히는 쪽)."""
    for part in argv[1:]:
        if part.startswith("-") and "=" in part:
            yield part.split("=", 1)[1]
        elif not part.startswith("-") or part == "-":
            yield part


def _is_inline_flag(token: str) -> bool:
    if token.startswith("--eval") or token.startswith("--exec"):
        return True
    if token.startswith("--"):
        return False
    return token[:2] in {"-c", "-e", "-p", "-r"}


def device_command_refusal(argv: object, allowed: Iterable[str]) -> str | None:
    """기기에서 돌면 안 되는 argv 면 이유(브리지 오류 이름), 돌아도 되면 `None`.

    `allowed` 는 이 자리가 아는 실행 파일 집합이다 -- 서버는 상한(과 선언), 클라이언트는 자기가
    고정한 목록. 비밀 경로는 서버와 같은 함수(`is_denied_secret_path`)로 본다.
    """
    from neos.coding.domain.approvals import is_denied_secret_path

    if not isinstance(argv, (list, tuple)) or not argv or len(argv) > MAX_ARGV_ITEMS:
        return "command_refused"
    if not all(isinstance(part, str) for part in argv):
        return "command_refused"
    parts = tuple(argv)
    if any("\0" in part or len(part) > MAX_ARGV_ITEM_CHARS for part in parts):
        return "command_refused"
    if sum(len(part) for part in parts) > MAX_ARGV_TOTAL_CHARS:
        return "command_refused"
    if any(_SECRET_REF_MARK in part.casefold() for part in parts):
        return "secret_path"
    executable = parts[0]
    if executable_name_refusal(executable) is not None:
        return "command_refused"
    if executable not in frozenset(allowed):
        return "command_not_allowed"
    # `python3.12` · `node22` 처럼 버전이 붙은 이름도 같은 인터프리터다.
    family = re.sub(r"[0-9.]+$", "", executable.casefold())
    if family in _INLINE_INTERPRETERS and any(_is_inline_flag(part) for part in parts[1:]):
        return "command_refused"
    for value in _operand_values(parts):
        if value and _escapes(value):
            return "path_escape"
        if value and is_denied_secret_path(value):
            return "secret_path"
    return None


__all__ = [
    "EXECUTABLE_NAME_RE",
    "MAX_ARGV_ITEMS",
    "MAX_ARGV_ITEM_CHARS",
    "MAX_ARGV_TOTAL_CHARS",
    "MAX_DECLARED_EXECUTABLES",
    "NEVER_ON_DEVICE",
    "device_command_refusal",
    "executable_name_refusal",
    "parse_executables",
]
