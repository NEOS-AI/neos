"""도구 이름의 와이어 인코딩 -- 공급자 경계에서만 쓴다 (2026-10-03, DECISIONS D106).

NEOS 의 도구 이름은 `read_file.v1` · `submit.v1` 처럼 **점**을 가진다. 공급자 API 는 그것을 받지
않는다 -- Anthropic 은 `^[a-zA-Z0-9_-]{1,128}$`, OpenAI 는 `^[a-zA-Z0-9_-]{1,64}$` 를 요구하고,
어기면 요청 전체가 400 이다(2026-10-03 실호출: "tools.0.custom.name: String should match pattern").
표본 #25 의 compose 자식이 첫 턴에서 매번 이것으로 죽었고, 같은 이름을 쓰는 코딩 루프·조사 자식도
라이브에서는 돌 수 없는 상태였다 -- 가짜 모델과 카세트는 이름을 검사하지 않는다.

**이름 자체는 바꾸지 않는다.** 이름은 레지스트리·스펙·게이트·원장·프론트 fixture 가 모두 읽는 계약이다.
바꾸는 것은 와이어에 실리는 모양뿐이고, 응답의 이름은 **같은 요청에서 만든 역맵**으로 되돌린다.

- 이미 유효한 이름은 그대로 간다 -- 그 요청의 바이트는 이전과 같다
- 두 이름이 같은 와이어 이름이 되면 **실패한다.** 접미사를 붙여 몰래 피하면 모델이 부른 이름이 어느 도구인지
  요청마다 달라질 수 있다
- 역맵에 없는 와이어 이름(모델이 지어낸 도구)은 그대로 돌려준다 -- 레지스트리가 모르는 도구로 거절한다
"""

from __future__ import annotations

import re
from typing import Iterable

from neos.coding.model.errors import CodingModelError

#: 두 공급자 규칙의 교집합. 길이는 더 짧은 OpenAI 쪽(64)을 따른다.
_INVALID = re.compile(r"[^A-Za-z0-9_-]")
WIRE_NAME_MAX = 64


def _encode(name: str) -> str:
    return (_INVALID.sub("_", name) or "_")[:WIRE_NAME_MAX]


class ToolNameCodec:
    def __init__(self, names: Iterable[str]) -> None:
        self._to_wire: dict[str, str] = {}
        self._from_wire: dict[str, str] = {}
        for name in sorted({str(item) for item in names if item}):
            wire = _encode(name)
            taken = self._from_wire.get(wire)
            if taken is not None and taken != name:
                raise CodingModelError("tool_name_collision", retryable=False)
            self._to_wire[name] = wire
            self._from_wire[wire] = name

    @classmethod
    def for_request(cls, request: object) -> "ToolNameCodec":
        """요청의 도구 목록 + 이력에 나온 이름(tool_use · tool_addition)으로 만든다.

        이력의 이름도 넣는 이유: 지난 턴에 쓰였다가 지금 목록에서 빠진 도구도 이력에는 남고,
        그 `tool_use` 블록도 같은 규칙으로 실려야 공급자가 받는다.
        """
        names: list[str] = [tool.name for tool in getattr(request, "tools", ())]
        for message in getattr(request, "messages", ()):
            for item in getattr(message, "content", ()):
                name = getattr(item, "name", None)
                if isinstance(name, str):
                    names.append(name)
        return cls(names)

    def wire(self, name: str) -> str:
        return self._to_wire.get(name) or _encode(name)

    def original(self, wire: str) -> str:
        return self._from_wire.get(wire, wire)
