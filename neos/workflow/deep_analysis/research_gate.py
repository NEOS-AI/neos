"""조사 자식의 도구 게이트 (J1.5, 로드맵 CHILD-GATE 의 조사 절반).

코딩 자식의 게이트(`neos/coding/loop/_durable/spawn.py` `_authorize_child_call`)와
**같은 모양**이다 -- `authorize(validated) -> (call, None) | (None, reason_code)`.
판정 자리는 부모 쪽이고, 여기서 부모는 오케스트레이터다. 포트는 정책을 갖지
않고 이 콜백만 부른다.

**규칙은 하나에서 나온다: 재실행기가 똑같이 다시 돌릴 수 있는 것만 돌린다.**
재실행기(`reexecutor.py`)는 새 샌드박스의 워크스페이스 루트에서
`python3 <script>` 를 인자·환경변수·stdin 없이 돌린다. 워커가 그것과 다르게
돌려서 얻은 출력은 채점에서 **재현될 수 없고**, 그 계산 클레임은 제출돼도
`E_COMPUTE_NOT_REPRODUCED` 로 죽는다. 뒤늦게 죽이는 것보다 돌리는 자리에서
막는 것이 싸고, 워커에게도 이유가 보인다.

argv allowlist(`python3` 만, `-c` 금지, 셸 금지)는 여기 없다 -- 레지스트리가
`command_allowlist={"python3"}` 로 이미 막는다(계약 §3.2). 같은 규칙을 두 곳에
두지 않는다.

이 모듈은 원장을 **로그에만** 쓴다(거절 기록). 원장 쓰기가 오케스트레이터
쪽에만 있다는 I2 는 그대로다 -- 게이트는 오케스트레이터가 짓고 포트에 넘긴다.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .sandbox import EVIDENCE_DIR

#: 원장 이벤트 kind. `tests/fixtures/deep_analysis_event_kinds.json` 에 있다.
DENIED_EVENT = "code_tool_denied"

EXECUTE_TOOL = "execute.v1"
WRITE_TOOL = "write_file.v1"
#: 조사 자식에게 여는 코딩 도구 (계약 §2 의 research 열 중 샌드박스 쪽).
#: `load_skill.v1`·`search.v1` 은 이번에 열지 않는다 -- 로드맵 J1.5 범위.
CODING_TOOLS = frozenset(
    {"list_tree.v1", "read_file.v1", "search_text.v1", WRITE_TOOL, EXECUTE_TOOL}
)
_READ_TOOLS = CODING_TOOLS - {WRITE_TOOL, EXECUTE_TOOL}

ARGV_SHAPE = "policy_research_argv_shape"
SCRIPT_PATH = "policy_research_script_path"
CWD = "policy_research_cwd"
IO = "policy_research_io"
EVIDENCE_READONLY = "policy_evidence_readonly"


def _under_evidence(path: str) -> bool:
    parts = tuple(part for part in PurePosixPath(path).parts if part != ".")
    return bool(parts) and parts[0] == EVIDENCE_DIR


def research_denial(name: str, data: dict[str, Any]) -> str | None:
    """이 호출을 막을 이유. 없으면 None. 순수 함수다.

    `data` 는 레지스트리가 **검증·정규화한** 입력이다 -- 경로는 이미
    워크스페이스 상대이고 `..` 는 이미 거절됐다.
    """
    if name in _READ_TOOLS:
        return None
    if name == WRITE_TOOL:
        # 증거는 원장이 넣은 바이트뿐이다(I4). Docker 경로는 커널이 이미
        # 막지만(읽기 전용 볼륨), 메모리·관리형 provider 는 증거를
        # 워크스페이스 안에 쓴다 -- 거기서는 이것이 첫 벽이다.
        if _under_evidence(str(data.get("path") or "")):
            return EVIDENCE_READONLY
        return None
    if name != EXECUTE_TOOL:
        return "tool_not_allowed"

    argv = [str(item) for item in data.get("argv") or ()]
    # 재실행기는 스크립트 하나만 넘긴다. 인자가 붙은 실행은 같은 출력을
    # 다시 낼 수 없다.
    if len(argv) != 2:
        return ARGV_SHAPE
    script = str(PurePosixPath(argv[1]))
    if not script.endswith(".py") or _under_evidence(script):
        return SCRIPT_PATH
    # 재실행기는 워크스페이스 루트에서 돈다. 다른 cwd 에서 상대 경로로
    # 증거를 읽는 스크립트는 거기서 파일을 못 찾는다.
    if str(data.get("cwd") or ".") != ".":
        return CWD
    if data.get("env") or data.get("stdin"):
        return IO
    return None


class ResearchGate:
    """질문 하나의 게이트. 거절은 원장에 남긴다 -- 조용한 거절 금지."""

    def __init__(self, ledger: Any, *, question_id: str) -> None:
        self._ledger = ledger
        self._question_id = question_id

    async def authorize(self, validated: Any) -> tuple[Any, str | None]:
        reason = research_denial(validated.name, dict(validated.input))
        if reason is None:
            return validated, None
        await self._ledger.log(
            DENIED_EVENT,
            self._question_id,
            {"tool": validated.name, "reason_code": reason},
        )
        return None, reason
