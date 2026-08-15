"""실제 LLM 을 호출해 토폴로지를 설계하는 `GraphDesigner` 구현체 (기능 플래그 뒤).

`neos.workflow.graph_designer` 는 계약(`GraphDesigner` 프로토콜, `DesignRequest`,
`parse_topology`)만 정의했다 -- 실제로 모델을 부르는 코드는 없었다. 이 모듈이 그
빈 자리를 채운다: 카탈로그와 질의를 프롬프트에 채워 모델에 보내고, 돌아온 텍스트를
JSON 으로 해석해 `parse_topology` 에 그대로 넘긴다.

이 클래스는 자신이 낸 토폴로지가 쓸만한지 판단하지 않는다. `validate_topology` 는
여기서 절대 호출하지 않는다 -- START 에서 모든 노드에 닿는지, requires 가
채워지는지, 예산 안에 드는지 같은 의미론적 타당성은 호출자(다음 태스크)의 몫이다.
만든 쪽이 스스로 통과 판정을 내리면 deep_analysis 하네스가 지키는
`judge != worker` 원칙이 이 자리에서만 깨진다 -- 그래서 의도적으로 분리해 둔다.

기본은 꺼짐이다(`graph_design_enabled=False`, `neos/config/schema.py`). 질의마다
LLM 으로 그래프를 새로 설계하는 비용(지연·비용·비결정성)은 이미 라우팅에서
"매 요청마다 LLM 으로 난이도를 분류" 하는 안을 기각한 것과 같은 이유로 무겁다 --
그래서 정적 그래프가 기본 경로로 남고, 이 경로는 명시적으로 켰을 때만 탄다.
"""

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from neos.config.settings import settings
from neos.workflow.contracts import NodeContract
from neos.workflow.graph_designer import (
    DesignRequest,
    InvalidDesignPayload,
    parse_topology,
)
from neos.workflow.topology import GraphTopology

# 모델이 프롬프트의 "JSON 만 출력하라" 지시를 어기고 ```json ... ``` 코드펜스로
# 감싸는 것은 실무에서 흔히 벌어지는, 내용이 아니라 형식의 문제다. 펜스 구문은
# 기계적으로 명확해서 벗겨내도 "애매한 입력을 되살리는" 것이 아니다. 반면
# 코드펜스 없이 산문 속에 JSON 이 섞인 경우(예: "여기 결과입니다: {...}")는
# 벗겨내지 않는다 -- 산문에서 JSON 조각을 추측해 꺼내는 것은 `parse_topology`
# 가 지키는 "형식이 애매하면 거부한다" 원칙을 이 앞단에서부터 깨는 것이기
# 때문이다. 그래서 이 파일은 딱 코드펜스만 벗기고, 그 밖의 텍스트는 그대로
# `json.loads` 에 넘겨 실패하게 둔다.
_MARKDOWN_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class _Model(Protocol):
    """`LlmGraphDesigner` 가 요구하는 모델의 최소 형태.

    LangChain 의 `BaseLanguageModel.ainvoke` 와 같은 시그니처다 -- 실제
    프로바이더 객체도, 테스트의 `_FakeModel` 도 이 구조만 만족하면 된다.
    """

    async def ainvoke(self, prompt: str) -> Any: ...


class LlmGraphDesigner:
    """카탈로그와 질의를 모델에 보내 토폴로지 하나를 받아오는 설계자.

    `design()` 은 `parse_topology` 가 잡는 형식(shape)·어휘(vocabulary) 오류만
    `InvalidDesignPayload` 로 통일해 던진다. 그 이상의 검증(START 도달성,
    requires 충족, 예산)은 하지 않는다 -- 호출자가 별도로 `validate_topology`
    를 돌려야 한다.
    """

    def __init__(
        self,
        model: _Model,
        prompt_path: Path,
        *,
        timeout_sec: float | None = None,
    ) -> None:
        self._model = model
        self._prompt_path = prompt_path
        # 생략하면 설정값(`neos/config/schema.py` 의 `graph_design_timeout_sec`)
        # 을 생성 시점에 읽는다 -- 호출마다 다시 읽지 않는 이유는, 같은
        # designer 인스턴스가 실행 중에 설정이 바뀌어도 흔들리지 않게 하기
        # 위해서다. 테스트는 `timeout_sec` 을 명시적으로 넘겨 이 기본값을
        # 우회한다.
        self._timeout_sec = (
            timeout_sec
            if timeout_sec is not None
            else settings.config.workflow.graph_design_timeout_sec
        )

    async def design(self, request: DesignRequest) -> GraphTopology:
        prompt = self._render_prompt(request)

        # 타임아웃은 여기서 삼키지 않고 그대로 전파한다 -- 정적 그래프로
        # 폴백할지는 호출자가 결정할 몫이지, 이 designer 가 스스로 판단할
        # 몫이 아니다(자신의 산출물을 스스로 승인하지 않는다는 원칙과 같다).
        response = await asyncio.wait_for(
            self._model.ainvoke(prompt), timeout=self._timeout_sec
        )
        payload = _parse_json_payload(_extract_text(response))

        known_nodes = frozenset(contract.node for contract in request.catalog)
        return parse_topology(payload, known_nodes=known_nodes)

    def _render_prompt(self, request: DesignRequest) -> str:
        template = self._prompt_path.read_text(encoding="utf-8")
        return template.format(
            query_text=request.query,
            node_catalog=_render_catalog(request.catalog),
            budget=request.budget,
        )


def _render_catalog(catalog: Sequence[NodeContract]) -> str:
    """노드 계약 목록을 프롬프트에 넣을 사람이 읽을 수 있는 텍스트로 바꾼다.

    `frozenset` 은 순서가 없으므로, 매 호출마다 프롬프트가 달라지지 않도록
    정렬해 나열한다.
    """

    if not catalog:
        return "(카탈로그가 비어 있다)"

    lines = []
    for contract in catalog:
        reads = ", ".join(sorted(contract.reads)) or "-"
        writes = ", ".join(sorted(contract.writes)) or "-"
        requires = ", ".join(sorted(contract.requires)) or "-"
        lines.append(
            f"- {contract.node}: reads=[{reads}] writes=[{writes}] requires=[{requires}]"
        )
    return "\n".join(lines)


def _extract_text(response: Any) -> str:
    """모델 응답에서 텍스트를 뽑는다.

    LangChain 계열 응답(`.content`)과 순수 문자열(테스트의 `_FakeModel`)을 모두
    받아들인다 -- `neos.utils.llm_wrapper.extract_text_from_response` 와 같은
    형태 판정 방식이지만, 이 모듈은 LLM 프레임워크를 임포트하지 않기 위해
    필요한 부분만 직접 판정한다.
    """

    if isinstance(response, str):
        return response
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return str(content)


def _parse_json_payload(text: str) -> Mapping:
    """모델 응답 텍스트를 JSON 매핑으로 해석한다.

    raw `json.JSONDecodeError` 를 그대로 새어나가게 두지 않는다 -- 호출자는
    `InvalidDesignPayload` 하나만 잡으면 "설계자가 낸 것이 뭐가 됐든 형식이
    잘못됐다"를 전부 처리할 수 있어야 한다.
    """

    stripped = _strip_markdown_fence(text)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise InvalidDesignPayload(
            f"invalid_json: 설계자 응답이 JSON 으로 해석되지 않는다 -- {exc}"
        ) from exc
    return payload


def _strip_markdown_fence(text: str) -> str:
    """```json ... ``` 코드펜스가 있으면 그 안쪽만 남긴다. 없으면 그대로 둔다."""

    stripped = text.strip()
    match = _MARKDOWN_FENCE.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped
