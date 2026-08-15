"""`LlmGraphDesigner` -- 기능 플래그 뒤에 숨은 실제 설계 서브에이전트.

이 모듈은 실제 LLM 을 절대 호출하지 않는다. `_FakeModel` 로 `ainvoke(prompt)` 만
구조적으로 흉내 내고, 응답 문자열을 바꿔가며 `LlmGraphDesigner.design` 이
- JSON 이 아닌 응답에서 `InvalidDesignPayload` 로 실패하는지 (raw parse
  에러가 새어나가지 않는지),
- 카탈로그에 없는 노드를 절대 지어내지 못하는지,
- 마크다운 코드펜스는 벗겨내되(기계적으로 명확한 변형) 코드펜스 없는
  산문(prose)에 섞인 JSON 은 거부하는지 (모호한 입력을 되살리지 않고
  거부한다는 `parse_topology` 의 원칙을 그대로 잇는다), 그리고 그 펜스
  제거가 언어 태그 없음/닫는 펜스 뒤 공백/펜스 두 개/닫히지 않은 펜스에서도
  고정된 대로 동작하는지,
- 확장 사고(extended thinking) 모델처럼 `.content` 가 블록 리스트로 오는
  응답도 text 블록만 골라내 파싱하는지 (`neos.utils.llm_wrapper.
  extract_text_from_response` 재사용을 고정한다),
- 타임아웃이 실제로 걸리는지
를 검증한다.

`design()` 은 자신이 낸 토폴로지를 검증하지 않는다 -- `validate_topology` 는
여기서 절대 호출하지 않는다. 검증은 호출자(Task 8)의 몫이다.
"""

import asyncio
from pathlib import Path

import pytest

from neos.workflow import graph_designer as graph_designer_module
from neos.workflow.contracts import NodeContract
from neos.workflow.graph_designer import DesignRequest, InvalidDesignPayload
from neos.workflow.graph_designer_llm import LlmGraphDesigner

# 실제 운영에서 쓰는 프롬프트 파일 그대로를 가리킨다 -- 테스트가 별도의 가짜
# 프롬프트를 만들지 않고, Task 6 이 이스케이프해 둔 진짜 파일을 그대로 태운다.
PROMPT = Path(graph_designer_module.__file__).parent / "prompts" / "graph_design.md"


def _contract_for(name: str) -> NodeContract:
    """테스트용 최소 노드 계약 -- 카탈로그에 이름 하나만 있으면 된다."""

    return NodeContract(
        node=name,
        reads=frozenset(),
        writes=frozenset(),
        requires=frozenset(),
        handler=lambda state: state,
    )


class _FakeModel:
    """`ainvoke(prompt) -> str` 만 구현하는 결정론적 가짜 모델.

    `delay_sec` 을 주면 그만큼 잠들었다가 응답한다 -- 타임아웃 경로를 실제로
    거치게 하기 위해서다.
    """

    def __init__(self, response_text: str, *, delay_sec: float = 0.0) -> None:
        self._response_text = response_text
        self._delay_sec = delay_sec
        self.calls = 0

    async def ainvoke(self, prompt: str) -> str:
        self.calls += 1
        if self._delay_sec:
            await asyncio.sleep(self._delay_sec)
        return self._response_text


async def test_a_malformed_model_response_raises_invalid_design_payload() -> None:
    """JSON 이 아닌 응답은 raw `json.JSONDecodeError` 가 아니라
    `InvalidDesignPayload` 로 실패해야 한다 -- 파서 예외가 그대로 새어나가면
    안 된다."""

    designer = LlmGraphDesigner(model=_FakeModel("not json"), prompt_path=PROMPT)

    with pytest.raises(InvalidDesignPayload):
        await designer.design(DesignRequest(query="q", catalog=(), budget=1000))


async def test_the_designer_never_invents_a_node() -> None:
    """카탈로그에 없는 노드를 응답에 넣으면 `parse_topology` 의 어휘 검사가
    막는다 -- 설계자가 스스로 검증하지 않아도 이 관문은 항상 통과한다."""

    designer = LlmGraphDesigner(
        model=_FakeModel('{"nodes": ["ghost"], "edges": []}'), prompt_path=PROMPT
    )

    with pytest.raises(InvalidDesignPayload, match="unknown_node"):
        await designer.design(
            DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
        )


async def test_a_markdown_fenced_response_is_still_parsed() -> None:
    """모델이 프롬프트의 "JSON 만 출력하라" 지시를 어기고 ```json 코드펜스로
    감싸는 것은 실무에서 흔히 벌어지는, 내용이 아니라 형식의 문제다. 기계적으로
    명확하게 벗겨낼 수 있으므로 이 designer 는 코드펜스를 벗겨내고 파싱한다."""

    fenced = '```json\n{"nodes": ["a"], "edges": [["__start__", "a"], ["a", "__end__"]]}\n```'
    designer = LlmGraphDesigner(model=_FakeModel(fenced), prompt_path=PROMPT)

    topology = await designer.design(
        DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
    )

    assert topology.nodes == ("a",)


async def test_leading_prose_without_fences_is_rejected() -> None:
    """코드펜스 없이 산문 뒤에 JSON 을 붙인 응답은 벗겨내지 않고 거부한다.
    코드펜스 제거는 기계적으로 명확한 형식 변형이지만, 산문 속 JSON을
    "최선을 다해" 찾아 꺼내는 것은 `parse_topology` 가 지키는
    "애매한 입력은 되살리지 않고 거부한다" 원칙을 이 designer 에서부터
    깨는 것이므로 하지 않는다."""

    prosy = 'Here is the topology you asked for: {"nodes": ["a"], "edges": []}'
    designer = LlmGraphDesigner(model=_FakeModel(prosy), prompt_path=PROMPT)

    with pytest.raises(InvalidDesignPayload):
        await designer.design(
            DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
        )


async def test_a_slow_model_times_out() -> None:
    """모델 호출이 `timeout_sec` 을 넘으면 타임아웃으로 실패해야 한다 -- 이
    designer 는 스스로 정적 그래프로 폴백하지 않는다(그건 호출자의 몫이다).
    그저 시간이 오래 걸렸다는 사실을 감추지 않고 그대로 드러낸다."""

    designer = LlmGraphDesigner(
        model=_FakeModel('{"nodes": [], "edges": []}', delay_sec=0.2),
        prompt_path=PROMPT,
        timeout_sec=0.01,
    )

    with pytest.raises(TimeoutError):
        await designer.design(DesignRequest(query="q", catalog=(), budget=1000))


async def test_a_well_formed_response_reaches_parse_topology_unvalidated() -> None:
    """정상 응답은 `parse_topology` 를 그대로 통과해 `GraphTopology` 가 된다.
    이 designer 는 `validate_topology` 를 호출하지 않으므로, START 에 닿지
    않는 등 의미론적으로 허술한 토폴로지도 여기서는 그대로 반환된다 -- 그
    판단은 호출자의 몫이다."""

    designer = LlmGraphDesigner(
        model=_FakeModel('{"nodes": ["a"], "edges": [["__start__", "a"]]}'),
        prompt_path=PROMPT,
    )

    topology = await designer.design(
        DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
    )

    assert topology.nodes == ("a",)
    assert topology.edges == (("__start__", "a"),)


async def test_a_thinking_block_response_is_still_parsed() -> None:
    """확장 사고(extended thinking) 모델은 `.content` 가 블록 리스트로 온다
    (예: opus-5 의 adaptive thinking). 그 리스트에서 text 블록만 골라내지
    않고 `str(list)` 로 뭉뚱그리면, 멀쩡한 설계 응답이 JSON 파싱 실패로
    오판된다 -- 이 테스트가 그 회귀를 고정한다."""

    class _ThinkingResponse:
        content = [
            {"type": "thinking", "thinking": "이 질의에는 노드 a 하나면 충분하다"},
            {
                "type": "text",
                "text": '{"nodes": ["a"], "edges": [["__start__", "a"], ["a", "__end__"]]}',
            },
        ]

    class _ThinkingModel:
        async def ainvoke(self, prompt: str) -> _ThinkingResponse:
            return _ThinkingResponse()

    designer = LlmGraphDesigner(model=_ThinkingModel(), prompt_path=PROMPT)

    topology = await designer.design(
        DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
    )

    assert topology.nodes == ("a",)


async def test_fence_stripper_handles_no_language_tag() -> None:
    """```` ``` ```` 만 있고 `json` 언어 태그가 없어도 벗겨내야 한다."""

    fenced = '```\n{"nodes": ["a"], "edges": []}\n```'
    designer = LlmGraphDesigner(model=_FakeModel(fenced), prompt_path=PROMPT)

    topology = await designer.design(
        DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
    )

    assert topology.nodes == ("a",)


async def test_fence_stripper_handles_trailing_whitespace_after_closing_fence() -> None:
    """닫는 펜스 뒤에 공백/개행이 남아 있어도 벗겨내야 한다."""

    fenced = '```json\n{"nodes": ["a"], "edges": []}\n```   \n\n'
    designer = LlmGraphDesigner(model=_FakeModel(fenced), prompt_path=PROMPT)

    topology = await designer.design(
        DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
    )

    assert topology.nodes == ("a",)


async def test_fence_stripper_takes_the_first_of_two_fenced_blocks() -> None:
    """펜스가 두 개면 첫 번째 것만 취한다 -- 정규식이 non-greedy 이기 때문이다.
    이 동작을 명시적으로 고정해, 나중에 "개선"한답시고 마지막 블록을 취하거나
    여러 블록을 합치는 식으로 바뀌지 않게 한다."""

    two_blocks = (
        '```json\n{"nodes": ["a"], "edges": []}\n```\n'
        "설명 다음에 또 다른 펜스가 온다.\n"
        '```json\n{"nodes": ["ghost"], "edges": []}\n```'
    )
    designer = LlmGraphDesigner(model=_FakeModel(two_blocks), prompt_path=PROMPT)

    topology = await designer.design(
        DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
    )

    # 두 번째 블록의 "ghost" 가 아니라 첫 번째 블록의 "a" 가 취해졌다.
    assert topology.nodes == ("a",)


async def test_fence_stripper_rejects_an_unclosed_fence() -> None:
    """여는 펜스만 있고 닫는 펜스가 없으면 정규식이 매치하지 않는다 -- 원문이
    그대로 `json.loads` 에 넘어가 실패로 닫힌다(fail closed). 코드펜스가
    없는 산문처럼, 애매한 입력을 되살리려 하지 않는다."""

    unclosed = '```json\n{"nodes": ["a"], "edges": []}\n'
    designer = LlmGraphDesigner(model=_FakeModel(unclosed), prompt_path=PROMPT)

    with pytest.raises(InvalidDesignPayload):
        await designer.design(
            DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
        )


async def test_the_query_and_catalog_reach_the_prompt() -> None:
    """프롬프트가 실제로 질의문과 카탈로그를 담아 모델에 전달되는지 -- fake
    모델이 받은 프롬프트 문자열을 그대로 캡처해 확인한다."""

    captured: dict[str, str] = {}

    class _CapturingModel:
        async def ainvoke(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return '{"nodes": [], "edges": []}'

    designer = LlmGraphDesigner(model=_CapturingModel(), prompt_path=PROMPT)

    await designer.design(
        DesignRequest(
            query="이것은 유일무이한 질의다", catalog=(_contract_for("a"),), budget=42
        )
    )

    assert "이것은 유일무이한 질의다" in captured["prompt"]
    assert "a" in captured["prompt"]
    assert "42" in captured["prompt"]
