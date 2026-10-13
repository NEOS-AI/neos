"""설계 그래프 → 순차 배선 (spec 2026-10-13 §4.10)."""

import pytest

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.enums import WorkflowNode as N
from neos.workflow.runtime.designed import designed_wiring
from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology, validate_topology
from neos.workflow.wiring import WiringError

pytestmark = pytest.mark.no_db

_CHAIN = (N.QUERY_CLS.value, N.SEARCH_ORCHESTRATOR.value, N.RESP_GENERATOR.value)


def _chain() -> GraphTopology:
    return GraphTopology(
        nodes=_CHAIN,
        edges=((START, _CHAIN[0]), (_CHAIN[0], _CHAIN[1]), (_CHAIN[1], _CHAIN[2]), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


def _fanout() -> GraphTopology:
    return GraphTopology(
        nodes=_CHAIN,
        edges=((START, _CHAIN[0]), (_CHAIN[0], _CHAIN[1]), (_CHAIN[0], _CHAIN[2]), (_CHAIN[1], END), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


def _workflow():
    import neos.workflow.graph  # noqa: F401 -- 계약 등록

    from neos.workflow.graph import MultiAgentWorkflow

    return MultiAgentWorkflow.__new__(MultiAgentWorkflow)


def test_a_chain_becomes_bound_static_edges() -> None:
    wiring = designed_wiring(_chain(), _workflow(), gated_nodes=frozenset())
    assert [spec.name for spec in wiring.nodes] == list(_CHAIN)
    assert all(callable(spec.handler) for spec in wiring.nodes)
    assert [(e.source, e.target) for e in wiring.edges][0] == (START, _CHAIN[0])
    assert wiring.branches == ()


def test_gated_nodes_present_become_interrupts() -> None:
    gated = frozenset({N.SEARCH_ORCHESTRATOR.value})
    wiring = designed_wiring(_chain(), _workflow(), gated_nodes=gated)
    assert wiring.interrupt_before == (N.SEARCH_ORCHESTRATOR.value,)


def test_parallel_designs_are_violations_only_when_disallowed() -> None:
    allowed = validate_topology(_fanout(), contracts=NODE_CONTRACTS)
    disallowed = validate_topology(_fanout(), contracts=NODE_CONTRACTS, allow_parallel=False)
    assert not [v for v in allowed if v.rule == "parallel_unsupported"]
    assert [v.node for v in disallowed if v.rule == "parallel_unsupported"] == [_CHAIN[0]]


def test_a_template_node_routes_to_itself_or_its_single_follower() -> None:
    class Host:
        template_names = frozenset({"tpl"})

        def handler_for(self, node):
            async def run(state):
                return {}

            return run

        def route_for(self, node, done):
            done = list(done)
            return lambda state: [node] if state.get("again") else done

    topology = GraphTopology(
        nodes=(_CHAIN[0], "tpl", _CHAIN[2]),
        edges=((START, _CHAIN[0]), (_CHAIN[0], "tpl"), ("tpl", "tpl"), ("tpl", _CHAIN[2]), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    wiring = designed_wiring(topology, _workflow(), subagent_host=Host(), gated_nodes=frozenset())
    tpl = next(spec for spec in wiring.nodes if spec.name == "tpl")
    assert tpl.wrapped is False
    branch = next(b for b in wiring.branches if b.source == "tpl")
    assert branch.router({"again": True}) == "tpl"
    assert branch.router({}) == _CHAIN[2]


def test_a_template_fanning_out_is_rejected() -> None:
    class Host:
        template_names = frozenset({"tpl"})

        def handler_for(self, node):
            return lambda state: {}

        def route_for(self, node, done):
            done = list(done)
            return lambda state: done

    topology = GraphTopology(
        nodes=("tpl", _CHAIN[1], _CHAIN[2]),
        edges=((START, "tpl"), ("tpl", _CHAIN[1]), ("tpl", _CHAIN[2]), (_CHAIN[1], END), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    wiring = designed_wiring(topology, _workflow(), subagent_host=Host(), gated_nodes=frozenset())
    branch = next(b for b in wiring.branches if b.source == "tpl")
    with pytest.raises(WiringError, match="parallel"):
        branch.router({})


@pytest.mark.asyncio
async def test_resume_without_a_stored_topology_uses_the_static_runner(monkeypatch) -> None:
    from neos.workflow.runtime.designed import resume_execution_graph
    from tests.workflow.support.stub_workflow import StubPlan, stub_workflow

    workflow = stub_workflow(monkeypatch, StubPlan(), runtime="native")
    graph = await resume_execution_graph(workflow, {"x": 1}, use_checkpointer=True)
    assert graph.source == "static" and graph.runner is not None


@pytest.mark.asyncio
async def test_resume_with_a_stored_chain_uses_the_designed_runner(monkeypatch) -> None:
    from neos.workflow.runtime.designed import resume_execution_graph
    from neos.workflow.topology import topology_to_payload
    from tests.workflow.support.stub_workflow import StubPlan, stub_workflow

    # `_chain()` 은 응답 생성기의 requires 를 채우지 못해 현재 계약 검증을 지나지 않는다 --
    # 재개 왕복 관문(`tests/workflow/test_designed_resume_round_trip.py`)이 쓰는 사슬을 쓴다.
    resumable = (
        N.QUERY_CLS.value,
        N.SEARCH_ORCHESTRATOR.value,
        "analysis_orchestrator",
        "generation_orchestrator",
        "execution_approval",
        N.RESP_GENERATOR.value,
    )
    topology = GraphTopology(
        nodes=resumable,
        edges=(
            (START, resumable[0]),
            *((resumable[i], resumable[i + 1]) for i in range(len(resumable) - 1)),
            (resumable[-1], END),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    workflow = stub_workflow(monkeypatch, StubPlan(), runtime="native")
    graph = await resume_execution_graph(
        workflow, {"execution_topology": topology_to_payload(topology)}, use_checkpointer=True
    )
    assert graph.source == "designed"
    assert tuple(graph.nodes) == resumable
    assert graph.runner is not None
