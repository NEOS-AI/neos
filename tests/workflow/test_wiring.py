"""배선 표 (spec 2026-10-13 §4.1).

표가 정적 그래프의 단일 원천이 된다. 이 파일은 (1) 표의 규칙과 (2) 표가 지금
`_create_workflow_graph` 의 배선과 같다는 것을 고정한다.
"""

import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.enums import WorkflowPathway as P
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology import START
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


# -- AST 추출기와의 동등성 (Task 5 에서 추출기와 함께 지운다) -----------------


@pytest.mark.parametrize("flags", list(_all_flag_combinations()), ids=_flag_id)
def test_the_table_equals_the_ast_extraction(flags) -> None:
    """노드 집합 · 엣지 다중집합 · 반복 상한이 옛 추출기와 같다. 해시만 보면 무엇이
    다른지 말하지 않으므로 집합으로 비교한다(메모리: 개수가 아니라 이름으로)."""
    from neos.workflow.topology_export import static_topology

    old = static_topology(flags=flags)
    new = topology_of(resolve_wiring(flags))
    assert set(new.nodes) == set(old.nodes)
    assert Counter(new.edges) == Counter(old.edges)
    assert dict(new.loop_bounds) == dict(old.loop_bounds)
