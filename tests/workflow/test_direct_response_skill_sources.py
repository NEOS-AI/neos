"""skip 경로에서도 스킬이 돌면 직접 응답이 그 출처로 답한다 (spec §2).

출처는 `skill_sources` 에서만 온다. `search_results` 는 체크포인트 스레드에서
턴을 넘어 누적되므로(`operator.add`) 거기서 고르면 앞 턴의 출처가 섞인다.
"""

from unittest.mock import AsyncMock

import pytest

import neos.workflow.graph as graph_module
from neos.skills.base.search_results import SKILL_EXECUTOR_VIA
from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.enums import WorkflowNode
from neos.workflow.processors.response_generator import ResponseGenerator
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db


def _generator() -> ResponseGenerator:
    return ResponseGenerator.__new__(ResponseGenerator)


def _state(sources, search_results=()):
    return {
        "original_query": "최신 DiT 논문",
        "skill_sources": sources,
        "search_results": list(search_results),
        "conversation_context": "",
    }


def _skill_result(title, url, content):
    return SearchResult(source="arxiv", title=title, content=content, url=url, metadata={"skill": "arxiv", "via": SKILL_EXECUTOR_VIA})


def test_skill_sources_are_numbered_into_the_prompt() -> None:
    prompt = _generator()._direct_response_prompt(
        _state([_skill_result("Paper A", "https://arxiv.org/abs/1", "alpha body")]), "ko"
    )
    assert "[출처]" in prompt
    assert "[1] Paper A — https://arxiv.org/abs/1" in prompt
    assert "alpha body" in prompt
    assert "외부 검색이 필요 없다고" not in prompt


def test_skill_tagged_results_only_in_search_results_are_ignored() -> None:
    """앞 턴의 스킬 결과가 누적된 search_results 에 남아 있어도 이번 턴 출처가 아니다."""
    stale = _skill_result("Old", "https://old", "old body")
    prompt = _generator()._direct_response_prompt(_state(None, [stale]), "ko")
    assert "[출처]" not in prompt
    assert "Old" not in prompt


def test_results_from_other_sources_do_not_change_the_prompt() -> None:
    other = SearchResult(source="web", title="W", content="c", url="https://w", metadata={})
    with_other = _generator()._direct_response_prompt(_state([], [other]), "ko")
    without = _generator()._direct_response_prompt(_state([]), "ko")
    assert with_other == without
    assert "[출처]" not in without


def test_the_contract_declares_the_read() -> None:
    reads = NODE_CONTRACTS[WorkflowNode.DIRECT_RESPONSE.value].reads
    assert "skill_sources" in reads
    assert "search_results" not in reads


# -- 체크포인트 두 턴 회귀 ------------------------------------------------------


async def test_a_later_turn_without_skills_does_not_reuse_earlier_sources(monkeypatch) -> None:
    """웹 채팅은 thread_id=conversation_id 로 체크포인터를 쓴다. 실제 AgentState 스키마와
    실제 실행 노드·프롬프트 헬퍼를 MemorySaver 위에서 두 턴 돌린다."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    import neos.skills.executor as executor_module
    from neos.skills.executor import SkillExecutionOutcome, SkillStep
    from neos.workflow.state import AgentState

    monkeypatch.setattr(graph_module.settings, "SKILL_EXECUTION_ENABLED", True)
    result = _skill_result("Paper A", "https://arxiv.org/abs/1", "alpha body")
    fake = AsyncMock(return_value=SkillExecutionOutcome(results=(result,), steps=(SkillStep("arxiv", "ok", "ok", 3, 1),)))
    monkeypatch.setattr(executor_module, "execute_skill_calls", fake)

    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    generator = _generator()
    prompts: list[str] = []

    async def record(state):
        prompts.append(generator._direct_response_prompt(state, "ko"))
        return {"final_response": "ok"}

    builder = StateGraph(AgentState)
    builder.add_node("skill_executor", workflow._skill_executor_node)
    builder.add_node("direct_response", record)
    builder.add_edge(START, "skill_executor")
    builder.add_edge("skill_executor", "direct_response")
    builder.add_edge("direct_response", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "conversation-1"}}

    def turn(calls):
        state = workflow._create_initial_state({"user_id": "u", "session_id": "s", "query": "q"})
        state["skill_calls"] = calls
        return state

    await graph.ainvoke(turn([{"name": "arxiv", "params": {"query": "q"}, "reason": ""}]), config)
    await graph.ainvoke(turn([]), config)

    assert fake.await_count == 1
    assert "[출처]" in prompts[0]
    assert "[출처]" not in prompts[1]
