"""재개용 그래프 복원 -- 같은 토폴로지로 짓거나, 짓지 못하면 거부한다.

정적으로 흐르는 경로가 없다는 것이 이 모듈의 요점이다. 스펙 §2.1: 조용한 정적
재개는 복구가 아니라 원래 버그이며, 사용자에게는 승인이 처리된 것으로 보이고
실제로는 설계가 의도한 것과 다른 파이프라인이 돈다.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.resume_graph import ResumeGraphUnavailable, resume_graph_for
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology, topology_to_payload

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)
_DESIGNED = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


async def _workflow():
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=True)
    return workflow


@pytest.mark.asyncio
async def test_a_static_run_resumes_on_the_static_graph():
    """`execution_topology` 가 없는(정적) run 은 지금 동작 그대로 정적 그래프로
    재개한다 -- 이 모듈이 정적 run 까지 새로 짓기 시작하면 안 된다."""
    workflow = await _workflow()

    graph = await resume_graph_for(
        {"execution_topology": None}, workflow=workflow, checkpointer=MemorySaver()
    )

    assert graph is workflow.graph


@pytest.mark.asyncio
async def test_a_run_missing_the_topology_key_resumes_on_the_static_graph():
    """`execution_topology` 키 자체가 없는 상태(이 기능이 생기기 전에 쓰인
    체크포인트)도 `None` 과 같게 취급해 정적 그래프로 재개한다 -- 하위 호환."""
    workflow = await _workflow()

    graph = await resume_graph_for({}, workflow=workflow, checkpointer=MemorySaver())

    assert graph is workflow.graph


@pytest.mark.asyncio
async def test_an_empty_topology_payload_is_refused_not_downgraded():
    """`execution_topology` 가 빈 dict(`{}`)로 도착하는 경우 -- 잘린 JSON 컬럼,
    미래의 부분 상태 쓰기, 수동 DB 수정 등에서 나올 수 있다 -- 는 정적 run 이
    아니라 손상된 설계된 run 페이로드다. `if not payload:` 로 되돌리면 빈
    dict 가 falsy 라 로그도 503 도 없이 정적 그래프로 조용히 재개된다 --
    이 테스트가 그 회귀를 잡는다."""
    workflow = await _workflow()

    with pytest.raises(ResumeGraphUnavailable) as caught:
        await resume_graph_for(
            {"execution_topology": {}}, workflow=workflow, checkpointer=MemorySaver()
        )

    assert "payload" in caught.value.reason


@pytest.mark.asyncio
async def test_a_designed_run_resumes_on_a_rebuilt_graph():
    """라벨이 아니라 **컴파일된 그래프 자체**를 본다. 정적 그래프에
    source='designed' 를 붙여 놓아도 통과하는 단언은 이 배선을 지키지 못한다
    (G2 스펙 서두의 경고).

    `graph is not workflow.graph` 만으로는 부족하다 -- `resume_graph_for` 가
    실수로 매번 새로 컴파일한 **정적** 그래프(노드 28개)를 돌려줘도 그 단언은
    통과한다(정적 그래프도 매번 재구성하면 workflow.graph 와 다른 객체가 된다).
    노드 집합을 `issubset` 으로만 보는 것도 마찬가지로 부족하다 -- 설계된
    토폴로지(노드 5개)는 정적 그래프 노드 집합(28개)의 부분집합이라, 재개가
    정적 그래프를 돌려줘도 subset 단언은 통과한다. 그래서 노드 집합을
    **정확히**(설계된 노드 + LangGraph 가 항상 붙이는 `__start__` 센티널) 비교해
    두 실패 모드를 모두 잡는다."""
    workflow = await _workflow()

    graph = await resume_graph_for(
        {"execution_topology": topology_to_payload(_DESIGNED)},
        workflow=workflow,
        checkpointer=MemorySaver(),
    )

    assert graph is not workflow.graph
    assert set(graph.nodes) == set(_CHAIN) | {"__start__"}


@pytest.mark.asyncio
async def test_a_malformed_payload_is_refused_not_downgraded():
    """페이로드를 `GraphTopology` 로 못 되돌리면 정적 그래프로 조용히
    내려가지 않고 `ResumeGraphUnavailable` 을 올린다."""
    workflow = await _workflow()

    with pytest.raises(ResumeGraphUnavailable) as caught:
        await resume_graph_for(
            {"execution_topology": {"nodes": "not-a-list"}},
            workflow=workflow,
            checkpointer=MemorySaver(),
        )

    assert "payload" in caught.value.reason


@pytest.mark.asyncio
async def test_a_topology_that_no_longer_validates_is_refused():
    """멈춘 뒤 배포가 계약을 바꾸면 저장된 토폴로지는 더 이상 유효하지 않다.
    `build_ephemeral_workflow` 는 재검증하지 않는다고 자기 독스트링에 적어
    뒀으므로(스펙 §2.2), 재검증은 이 경로가 한다."""
    workflow = await _workflow()
    unknown = GraphTopology(
        nodes=("node_that_does_not_exist",),
        edges=(("__start__", "node_that_does_not_exist"), ("node_that_does_not_exist", "__end__")),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    with pytest.raises(ResumeGraphUnavailable) as caught:
        await resume_graph_for(
            {"execution_topology": topology_to_payload(unknown)},
            workflow=workflow,
            checkpointer=MemorySaver(),
        )

    assert "valid" in caught.value.reason


@pytest.mark.asyncio
async def test_the_rebuilt_graph_gates_the_same_nodes():
    """`interrupt_before` 는 저장하지 않고 지금 정책으로 다시 계산한다
    (스펙 §3.4). 게이트 노드가 있는 토폴로지는 재개 그래프에서도 게이트된다."""
    workflow = await _workflow()
    gated_chain = (*_CHAIN[:-1], "execution_approval", _CHAIN[-1])
    gated = GraphTopology(
        nodes=gated_chain,
        edges=(
            ("__start__", gated_chain[0]),
            *((gated_chain[i], gated_chain[i + 1]) for i in range(len(gated_chain) - 1)),
            (gated_chain[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    graph = await resume_graph_for(
        {"execution_topology": topology_to_payload(gated)},
        workflow=workflow,
        checkpointer=MemorySaver(),
    )

    assert "execution_approval" in graph.interrupt_before_nodes
