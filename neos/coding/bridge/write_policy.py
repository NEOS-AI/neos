"""기기 쓰기의 경로 규칙 -- 트랙 Q16b (BW6 · BW8).

서버 검증기(`catalog.check_device_input`)와 참조 클라이언트(`neos.bridge.tools`)가 **이 함수 하나**를
쓴다 -- 사본이 둘이면 한쪽만 새 이름을 알게 된다(B10 의 `is_denied_secret_path` 와 같은 이유).
무거운 import 가 없어야 한다: 클라이언트는 사용자 기기에서 돈다.

막는 것: 비밀 경로 · dot 성분(셸 설정 · `.git/` · `.github/` · `.vscode/` ...) · OS 가 열면 실행하는
확장자. 루트 자체(`.`)와 빈 경로도 거절한다.
"""

from __future__ import annotations

#: 더블클릭·로그인·탐색기가 **실행**하는 파일. 텍스트라도 쓰지 않는다.
LAUNCHABLE_SUFFIXES = frozenset(
    {
        ".app",
        ".bat",
        ".cmd",
        ".com",
        ".command",
        ".cpl",
        ".desktop",
        ".exe",
        ".hta",
        ".inf",
        ".jse",
        ".lnk",
        ".msc",
        ".msi",
        ".pif",
        ".plist",
        ".ps1",
        ".reg",
        ".scf",
        ".scr",
        ".scpt",
        ".service",
        ".terminal",
        ".tool",
        ".url",
        ".vbe",
        ".vbs",
        ".webloc",
        ".workflow",
        ".wsf",
    }
)


def _parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.replace("\\", "/").split("/") if part not in {"", "."})


def device_write_refusal(path: object) -> str | None:
    """쓰면 안 되는 경로면 이유(브리지 오류 이름), 써도 되면 `None`.

    상대 경로·`..` 검사는 이 함수의 몫이 아니다(읽기와 같은 경계가 먼저 본다).
    """
    from neos.coding.domain.approvals import is_denied_secret_path

    if not isinstance(path, str) or not _parts(path):
        return "write_path_refused"
    if is_denied_secret_path(path):
        return "secret_path"
    parts = _parts(path)
    if any(part.startswith(".") for part in parts):
        return "write_path_refused"
    name = parts[-1].casefold().rstrip(" .")
    if any(name.endswith(suffix) for suffix in LAUNCHABLE_SUFFIXES):
        return "write_path_refused"
    return None


__all__ = ["LAUNCHABLE_SUFFIXES", "device_write_refusal"]
