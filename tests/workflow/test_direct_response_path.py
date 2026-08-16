"""G1-a: 검색이 필요 없는 질의가 사과문을 받지 않는다.

`skip_orchestrators` 는 오케스트레이터를 건너뛰고 곧장 응답 생성으로 갔는데,
응답 생성기는 검색·분석·생성 **결과를 요약하는 일만** 한다. 셋이 다 비면
`_construct_final_response` 가 이 문장을 돌려준다:

    "죄송합니다. 요청하신 주제에 대한 관련 정보를 찾지 못했습니다."

그 경로로 오는 질의는 정확히 *검색이 필요 없다고 판정된 것*들이다 -- 인사와
잡담이 답 대신 사과를 받고 있었다.

**이 테스트가 필요한 이유가 따로 있다.** 토폴로지 검증기의 위반 핀
(`test_static_graph_contract.py`)은 이 수정을 감지하지 못한다.
`response_generator` 로 들어오는 경로 7개 중 여섯도 같은 세 키를 쓰지 않아
위반 서명이 동일하게 유지되기 때문이다(그 여섯은 스스로 `final_response` 를
채우므로 실제로는 멀쩡하다). 그러니 여기서 **행동**을 고정한다.
"""

import pytest

from neos.workflow.enums import WorkflowNode, WorkflowPathway
from neos.workflow.processors.response_generator import (
    _DIRECT_FALLBACKS,
    ResponseGenerator,
)

pytestmark = pytest.mark.no_db

_APOLOGY = (
    "죄송합니다. 요청하신 주제에 대한 관련 정보를 찾지 못했습니다. "
    "다른 키워드로 다시 시도해 보시기 바랍니다."
)


def _state(**overrides):
    from datetime import datetime

    state = {
        "original_query": "안녕하세요",
        "detected_language": "ko",
        "session_id": "s1",
        "user_id": "u1",
        "search_results": [],
        "analysis_results": [],
        "generation_results": [],
        "execution_steps": [],
        "execution_start": datetime.now(),
        "errors": [],
    }
    state.update(overrides)
    return state


def test_the_summarizer_still_apologises_when_it_has_nothing():
    """고친 것을 증명하려면 고치기 전 증상이 살아 있어야 한다.

    이 단언이 깨지면 `_construct_final_response` 의 폴백이 바뀐 것이고, 그러면
    아래 테스트들이 무엇을 막고 있는지도 다시 봐야 한다.
    """
    generator = ResponseGenerator.__new__(ResponseGenerator)

    assert generator._construct_final_response([], "ko") == _APOLOGY


@pytest.mark.asyncio
async def test_a_conversational_query_gets_an_answer_not_an_apology(monkeypatch):
    generator = ResponseGenerator.__new__(ResponseGenerator)

    class _LLM:
        async def ainvoke(self, _messages):
            return "안녕하세요! 무엇을 도와드릴까요?"

    monkeypatch.setattr(generator, "_get_llm", lambda **_kw: _LLM(), raising=False)
    monkeypatch.setattr(
        "neos.workflow.processors.response_generator.create_tracked_llm",
        lambda *, llm, **_kw: llm,
    )

    result = await generator.generate_direct_response(_state())

    assert result["final_response"] == "안녕하세요! 무엇을 도와드릴까요?"
    assert _APOLOGY not in result["final_response"]


@pytest.mark.asyncio
async def test_a_failing_llm_does_not_fall_back_to_the_apology(monkeypatch):
    """폴백이 사과문이면 이 노드는 아무것도 고치지 못한 것이다."""
    generator = ResponseGenerator.__new__(ResponseGenerator)

    class _LLM:
        async def ainvoke(self, _messages):
            raise TimeoutError("provider down")

    monkeypatch.setattr(generator, "_get_llm", lambda **_kw: _LLM(), raising=False)
    monkeypatch.setattr(
        "neos.workflow.processors.response_generator.create_tracked_llm",
        lambda *, llm, **_kw: llm,
    )

    result = await generator.generate_direct_response(_state())

    assert result["final_response"] == _DIRECT_FALLBACKS["ko"]
    assert _APOLOGY not in result["final_response"]


@pytest.mark.asyncio
async def test_an_empty_answer_is_treated_as_a_failure(monkeypatch):
    """LLM 이 공백만 돌려주면 사용자에게 빈 응답이 간다."""
    generator = ResponseGenerator.__new__(ResponseGenerator)

    class _LLM:
        async def ainvoke(self, _messages):
            return "   "

    monkeypatch.setattr(generator, "_get_llm", lambda **_kw: _LLM(), raising=False)
    monkeypatch.setattr(
        "neos.workflow.processors.response_generator.create_tracked_llm",
        lambda *, llm, **_kw: llm,
    )

    result = await generator.generate_direct_response(_state())

    assert result["final_response"] == _DIRECT_FALLBACKS["ko"]


@pytest.mark.asyncio
async def test_the_summarizer_preserves_what_the_direct_node_wrote(monkeypatch):
    """직접 답을 만들어도 다음 노드가 그것을 덮어쓰면 소용이 없다.

    `generate_response()` 의 첫 분기(`_preserve_existing_response`)가 그 계약이며,
    `task_scheduling_node` 가 쓰는 것과 같은 경로다.
    """
    generator = ResponseGenerator.__new__(ResponseGenerator)
    state = _state(final_response="직접 만든 답")

    result = await generator.generate_response(state)

    assert result["final_response"] == "직접 만든 답"
    assert result["execution_steps"][-1]["result"] == "preserved_existing_response"


def test_the_skip_pathway_no_longer_points_at_the_summarizer():
    """배선 자체를 고정한다 -- 누가 되돌리면 여기서 걸린다."""
    import inspect

    from neos.workflow.graph import MultiAgentWorkflow

    source = inspect.getsource(MultiAgentWorkflow._create_workflow_graph)
    skip = WorkflowPathway.SKIP_ORCHESTRATORS.value

    for line in source.splitlines():
        if "WorkflowPathway.SKIP_ORCHESTRATORS.value:" in line:
            assert WorkflowNode.DIRECT_RESPONSE.value.upper() in line.upper(), (
                f"skip 경로가 다시 요약기로 간다: {line.strip()}"
            )
    assert skip
