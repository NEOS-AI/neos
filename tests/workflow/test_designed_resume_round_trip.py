"""관문: 재개에 쓰인 그래프의 토폴로지가 멈출 때의 것과 같은가.

스펙 §1이 든 관문 그 자체다. 앞선 태스크들은 조각을 고정하고, 이 테스트는
조각이 이어지는지 본다 -- 상태에 실린 페이로드가 재개 경로를 통해 같은
그래프로 돌아오는가.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.config import settings as settings_module
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.resume_graph import resume_graph_for
from neos.workflow.topology import (
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    topology_from_payload,
)

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "execution_approval",
    "response_generator",
)
_GATED = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


class _FakeDesigner:
    async def design(self, request):
        return _GATED


@pytest.mark.asyncio
async def test_the_resume_graph_has_the_topology_the_run_stopped_on(monkeypatch):
    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    monkeypatch.setattr("neos.workflow.graph.get_checkpointer", _fake_get_checkpointer)
    monkeypatch.setattr(
        settings_module.settings.config.workflow, "graph_design_enabled", True
    )

    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=True)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "승인이 필요한 질의", "session_id": "s-round-trip"},
        use_checkpointer=True,
        span=None,
    )
    assert resolved.source == "designed"

    # 오케스트레이터가 상태에 실었을 값.
    payload = workflow.execution_topology_payload(resolved)

    resume_graph = await resume_graph_for(
        {"execution_topology": payload}, workflow=workflow, checkpointer=saver
    )

    # 관문: 재개 그래프의 토폴로지 정체성이 멈출 때의 것과 같다.
    assert topology_hash(topology_from_payload(payload)) == resolved.topology_hash
    assert resume_graph is not workflow.graph
    # `issubset` 만으로는 부족하다 -- 설계된 토폴로지의 노드는 항상 정적
    # 그래프 노드 집합의 부분집합이라, `resume_graph_for` 가 실수로 정적
    # 그래프를 돌려줘도 subset 단언은 그대로 통과한다(이 관문이 잡아야 할
    # 바로 그 실패를 놓친다). 그래서 노드 집합을 **정확히**(설계된 노드 +
    # LangGraph 가 항상 붙이는 `__start__` 센티널) 비교한다
    # (`tests/workflow/test_resume_graph.py` 가 먼저 겪은 함정).
    assert set(resume_graph.nodes) == set(_CHAIN) | {"__start__"}
    assert "execution_approval" in resume_graph.interrupt_before_nodes
