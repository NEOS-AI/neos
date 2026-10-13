"""배선 표 (spec 2026-10-13 §4.1).

표가 정적 그래프의 단일 원천이 된다. 이 파일은 (1) 표의 규칙과 (2) 표가 지금
`_create_workflow_graph` 의 배선과 같다는 것을 고정한다.
"""

import itertools
import json
from pathlib import Path

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.enums import WorkflowPathway as P
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology import END, START
from neos.workflow.wiring import (
    BRANCHES,
    DEFAULT_FLAGS,
    Branch,
    Route,
    WiringError,
    resolve_wiring,
    topology_of,
)

pytestmark = pytest.mark.no_db

_HASHES = Path(__file__).resolve().parents[1] / "fixtures" / "static_topology_hashes.json"
_KEYS = sorted(DEFAULT_FLAGS)


def _all_flag_combinations():
    for bits in itertools.product([False, True], repeat=len(_KEYS)):
        yield dict(zip(_KEYS, bits))


def _flag_id(flags):
    return ",".join(f"{key}={int(flags[key])}" for key in _KEYS)


def test_unknown_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="알 수 없는 플래그"):
        resolve_wiring({"skill_execusion": True})


def test_start_edge_comes_first() -> None:
    """LangGraph 조립 순서를 고정한 기존 테스트가 첫 엣지가 START 에서 나가길 요구한다."""
    wiring = resolve_wiring()
    assert wiring.edges[0].source == START
    assert wiring.edges[0].target == N.REFINEMENT_CHECKER.value


def test_skill_execution_switches_the_selector_targets() -> None:
    off = resolve_wiring({"skill_execution": False})
    on = resolve_wiring({"skill_execution": True})
    sel = N.SKILL_TOOL_SELECTOR.value
    off_map = off.path_map(next(b for b in off.branches if b.source == sel))
    on_map = on.path_map(next(b for b in on.branches if b.source == sel))
    assert off_map[P.SKIP_ORCHESTRATORS.value] == N.DIRECT_RESPONSE.value
    assert on_map[P.SKIP_ORCHESTRATORS.value] == N.SKILL_EXECUTOR.value
    assert on_map[P.USE_ORCHESTRATORS.value] == N.SKILL_EXECUTOR.value


def test_interrupts_follow_the_approval_flag() -> None:
    assert resolve_wiring({"execution_approval": False}).interrupt_before == ()
    assert resolve_wiring({"execution_approval": True}).interrupt_before == (
        N.EXECUTION_APPROVAL.value,
        N.MISSION_APPROVAL.value,
    )


def test_two_active_routes_for_one_label_are_rejected(monkeypatch) -> None:
    """같은 라벨에 켜진 경로가 둘이면 어느 쪽이 이기는지 조용히 정하지 않는다."""
    import neos.workflow.wiring as wiring_module

    clash = Branch(
        source=N.REFINEMENT_CHECKER.value,
        router="_should_refine_or_continue",
        routes=(
            Route("skip_refinement", N.CONVERSATION_CTX_PROC.value),
            Route("skip_refinement", N.QUERY_CLS.value),
        ),
    )
    monkeypatch.setattr(wiring_module, "BRANCHES", (clash,) + tuple(BRANCHES[1:]))
    with pytest.raises(WiringError, match="skip_refinement"):
        resolve_wiring()


def test_a_dangling_target_is_rejected(monkeypatch) -> None:
    import neos.workflow.wiring as wiring_module

    dangling = Branch(
        source=N.REFINEMENT_CHECKER.value,
        router="_should_refine_or_continue",
        routes=(Route("skip_refinement", "no_such_node"),),
    )
    monkeypatch.setattr(wiring_module, "BRANCHES", (dangling,) + tuple(BRANCHES[1:]))
    with pytest.raises(WiringError, match="no_such_node"):
        resolve_wiring()


def test_every_handler_and_router_exists_on_the_workflow() -> None:
    from neos.workflow.graph import MultiAgentWorkflow

    wiring = resolve_wiring()
    for spec in wiring.nodes:
        assert callable(getattr(MultiAgentWorkflow, spec.handler, None)), spec.handler
    for branch in wiring.branches:
        assert callable(getattr(MultiAgentWorkflow, branch.router, None)), branch.router


@pytest.mark.parametrize("flags", list(_all_flag_combinations()), ids=_flag_id)
def test_the_table_hash_matches_the_captured_static_hash(flags) -> None:
    """AST 추출기가 살아 있을 때 캡처한 64개 해시. 추출기를 지운 뒤에도 남는 고정점이다."""
    captured = json.loads(_HASHES.read_text(encoding="utf-8"))
    assert topology_hash(topology_of(resolve_wiring(flags))) == captured[_flag_id(flags)]


# -- 조립된 LangGraph 그래프와 표의 동등성 -------------------------------------


@pytest.mark.parametrize("flags", list(_all_flag_combinations()), ids=_flag_id)
def test_the_compiled_graph_has_exactly_the_tables_edges(flags) -> None:
    """어댑터가 표를 빠짐없이 옮겼는가. LangGraph 의 `get_graph()` 는 같은 쌍을 한 번만
    내므로 집합으로 비교한다(다중집합은 위의 해시 테스트가 지킨다)."""
    from langgraph.graph import StateGraph

    from neos.workflow.runtime.langgraph_adapter import compile_wiring
    from neos.workflow.state import AgentState

    class _Owner:
        def __getattr__(self, name):
            return lambda state: {}

    wiring = resolve_wiring(flags)
    compiled = compile_wiring(wiring, _Owner(), graph_factory=StateGraph, state_schema=AgentState)
    drawn = compiled.get_graph()
    lg_edges = {(edge.source, edge.target) for edge in drawn.edges}
    table_edges = set(topology_of(wiring).edges)
    assert lg_edges == table_edges
    assert set(drawn.nodes) - {START, END} == {spec.name for spec in wiring.nodes}


def test_every_node_spec_names_its_contract_handler() -> None:
    """표의 `handler` 문자열이 그 노드 계약의 핸들러와 같다 -- 표와 `@node_contract` 가
    서로 다른 메서드를 가리키면 배선은 맞아도 엉뚱한 핸들러가 돈다."""
    import neos.workflow.graph  # noqa: F401 -- 계약을 등록한다
    from neos.workflow.contracts import NODE_CONTRACTS

    wiring = resolve_wiring({key: True for key in DEFAULT_FLAGS})
    mismatched = {
        spec.name: (spec.handler, NODE_CONTRACTS[spec.name].handler.__name__)
        for spec in wiring.nodes
        if spec.handler != NODE_CONTRACTS[spec.name].handler.__name__
    }
    assert mismatched == {}
    assert len(wiring.nodes) == len(NODE_CONTRACTS)
