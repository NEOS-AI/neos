"""`design_graph_or_fallback` -- 설계·검증·폴백이 만나는 단 하나의 관문.

설계 서브에이전트(`GraphDesigner`)는 토폴로지를 제안할 뿐 스스로 승인하지
않는다(`neos.workflow.graph_designer`). `validate_topology` 는 그 제안이
성립하는지만 계산할 뿐 누구를 부를지 모른다(`neos.workflow.topology`). 이
모듈은 그 둘을 하나로 엮고, 네 경로 -- 요청·승인·거부·폴백 -- 가 각각 이벤트를
남기게 한다.

이 파일이 고정하는 불변식은 하나다: **사유 없는 폴백은 조용한 degrade 와
구별되지 않는다.** 거부 이벤트는 어느 규칙이 어느 노드에서 깨졌는지 싣고,
폴백 이벤트는 예외든 타임아웃이든 사유를 싣는다. 이벤트가 없는 경로는 이
스펙에서 성공과 실패를 구별할 수 없는 것과 같다.
"""

import asyncio

from neos.workflow.contracts import NodeContract
from neos.workflow.enums import WorkflowNode
from neos.workflow.graph_design_ledger import (
    DesignOutcome,
    LedgerEvent,
    design_graph_or_fallback,
)
from neos.workflow.graph_designer import (
    DesignRequest,
    FakeGraphDesigner,
    InvalidDesignPayload,
)
from neos.workflow.topology import END, START, GraphTopology

KINDS = (
    "graph_design_requested",
    "graph_design_rejected",
    "graph_design_accepted",
    "graph_design_fallback",
)


def _contract(node: str, *, requires: tuple[str, ...] = ()) -> NodeContract:
    """테스트용 최소 노드 계약. `requires` 는 항상 `reads` 의 부분집합이어야
    한다는 `NodeContract.__post_init__` 제약을 그대로 만족시킨다."""

    return NodeContract(
        node=node,
        reads=frozenset(requires),
        writes=frozenset(),
        requires=frozenset(requires),
        handler=lambda state: state,
    )


def _contracts() -> dict[str, NodeContract]:
    """검증 대상 토폴로지들이 함께 쓰는 계약 카탈로그.

    'a' 는 아무것도 요구하지 않아 `_valid_topology` 를 그대로 통과시키고,
    'integrate' 는 'search_results' 를 요구하지만 이 카탈로그 어디서도 그
    키를 쓰는 노드가 없어 `_topology_missing_requires` 를 반드시 위반시킨다.
    'b' 는 해시 테스트들이 쓰는 두 번째 노드 -- 계약이 없으면 `missing_contract`
    가 떠 그 토폴로지가 거부되고 만다(FIX 1: 계약 없는 노드는 fail-closed).
    """

    return {
        "a": _contract("a"),
        "b": _contract("b"),
        "integrate": _contract("integrate", requires=("search_results",)),
    }


def _valid_topology() -> GraphTopology:
    return GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))


def _topology_missing_requires() -> GraphTopology:
    return GraphTopology(
        nodes=("integrate",), edges=((START, "integrate"), ("integrate", END))
    )


def _request() -> DesignRequest:
    return DesignRequest(query="q", catalog=(), budget=1000)


class _RaisingDesigner:
    """`design()` 호출 즉시 주어진 예외를 던지는 테스트 더블."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def design(self, request: DesignRequest) -> GraphTopology:
        raise self._exc


class _HangingDesigner:
    """영원히 응답하지 않는 테스트 더블 -- 타임아웃 경로를 실제로 거치게 한다."""

    async def design(self, request: DesignRequest) -> GraphTopology:
        await asyncio.Event().wait()
        raise AssertionError("타임아웃이 먼저 걸려야 하므로 여기 도달하면 안 된다")


async def test_a_valid_design_is_accepted_and_recorded() -> None:
    outcome = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_valid_topology()),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    kinds = [e.kind for e in outcome.events]
    assert kinds == ["graph_design_requested", "graph_design_accepted"]
    assert outcome.topology is not None


async def test_a_rejected_design_records_the_rule_and_node() -> None:
    """거부 이벤트는 어느 규칙이 어느 노드에서 깨졌는지 실어야 한다.

    사유 없는 폴백은 '조용한 degrade' 와 구별되지 않는다.
    """
    outcome = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_topology_missing_requires()),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    rejected = next(e for e in outcome.events if e.kind == "graph_design_rejected")
    assert rejected.payload["violations"]
    assert "unsatisfied_requires" in {v["rule"] for v in rejected.payload["violations"]}
    assert outcome.topology is None


async def test_a_designer_error_falls_back_with_a_reason() -> None:
    outcome = await design_graph_or_fallback(
        designer=_RaisingDesigner(InvalidDesignPayload("unknown_node: ghost")),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    fallback = next(e for e in outcome.events if e.kind == "graph_design_fallback")
    assert "unknown_node" in fallback.payload["reason"]
    assert outcome.topology is None


async def test_a_designer_timeout_falls_back_with_a_reason() -> None:
    outcome = await design_graph_or_fallback(
        designer=_HangingDesigner(),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
        timeout_sec=0.01,
    )
    fallback = next(e for e in outcome.events if e.kind == "graph_design_fallback")
    assert fallback.payload["reason"] == "timeout"
    assert outcome.topology is None


async def test_no_path_escapes_without_a_closing_event() -> None:
    """네 경로(요청·승인·거부·폴백) 중 어느 것을 타든, 항상
    `graph_design_requested` 뒤에 정확히 하나의 종결 이벤트가 남아야 한다.
    KINDS 밖의 이벤트 종류가 새로 생기지 않았는지도 함께 고정한다."""

    outcomes = [
        await design_graph_or_fallback(
            designer=FakeGraphDesigner(_valid_topology()),
            request=_request(),
            contracts=_contracts(),
        ),
        await design_graph_or_fallback(
            designer=FakeGraphDesigner(_topology_missing_requires()),
            request=_request(),
            contracts=_contracts(),
        ),
        await design_graph_or_fallback(
            designer=_RaisingDesigner(RuntimeError("model client blew up")),
            request=_request(),
            contracts=_contracts(),
        ),
    ]
    for outcome in outcomes:
        assert isinstance(outcome, DesignOutcome)
        kinds = [e.kind for e in outcome.events]
        assert kinds[0] == "graph_design_requested"
        assert len(kinds) == 2
        assert kinds[1] in KINDS
        for event in outcome.events:
            assert isinstance(event, LedgerEvent)


async def test_a_bare_exception_from_the_designer_also_falls_back() -> None:
    """`InvalidDesignPayload` 도 타임아웃도 아닌 예외(예: 모델 클라이언트가
    던지는 `RuntimeError`)도 조용히 새어나가지 않고 사유를 실어 폴백해야
    한다 -- 이 함수를 나가는 모든 경로가 이벤트를 남긴다는 불변식은 예외의
    종류를 가리지 않는다."""

    outcome = await design_graph_or_fallback(
        designer=_RaisingDesigner(RuntimeError("model client blew up")),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    fallback = next(e for e in outcome.events if e.kind == "graph_design_fallback")
    assert "model client blew up" in fallback.payload["reason"]
    assert outcome.topology is None


def _accepted_event(outcome: DesignOutcome) -> LedgerEvent:
    return next(e for e in outcome.events if e.kind == "graph_design_accepted")


async def test_the_accepted_payload_carries_a_stable_topology_hash() -> None:
    """같은 설계를 두 번 승인해도 해시가 같아야 한다 -- 이 해시가 정적 run 과
    비교할 수 있는 안정적 식별자라는 스펙 §7-5 의 요구를 고정한다.

    이 테스트는 해시의 안정성만 본다 -- `mandatory` 기본값(response_generator
    필수화, I1)과는 무관하므로 `mandatory=()` 를 명시적으로 넘겨 그 게이트를
    끈다. `_valid_topology()` 의 노드 'a' 는 response_generator 가 아니라서,
    기본값을 그대로 두면 이 설계는 `missing_mandatory` 로 거부되어
    `graph_design_accepted` 이벤트 자체가 없어진다."""

    outcome_1 = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_valid_topology()),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    outcome_2 = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_valid_topology()),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    hash_1 = _accepted_event(outcome_1).payload["topology_hash"]
    hash_2 = _accepted_event(outcome_2).payload["topology_hash"]
    assert hash_1
    assert hash_1 == hash_2


async def test_reordered_edges_produce_the_same_hash() -> None:
    """같은 그래프를 엣지 나열 순서만 다르게 제안해도 논리적으로 같은
    토폴로지이므로 해시가 같아야 한다 -- 순서는 우연(모델이 JSON 을 낸 순서)일
    뿐 그래프의 정체성이 아니다.

    'a'/'b' 는 response_generator 가 아니므로, `mandatory` 기본값(I1)을 그대로
    두면 이 설계들은 `missing_mandatory` 로 거부된다 -- 이 테스트는 해시
    안정성만 보므로 그 게이트를 `mandatory=()` 로 명시적으로 끈다."""

    ordered = GraphTopology(
        nodes=("a", "b"), edges=((START, "a"), ("a", "b"), ("b", END))
    )
    reordered = GraphTopology(
        nodes=("a", "b"), edges=(("b", END), ("a", "b"), (START, "a"))
    )

    outcome_ordered = await design_graph_or_fallback(
        designer=FakeGraphDesigner(ordered),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    outcome_reordered = await design_graph_or_fallback(
        designer=FakeGraphDesigner(reordered),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )

    assert (
        _accepted_event(outcome_ordered).payload["topology_hash"]
        == _accepted_event(outcome_reordered).payload["topology_hash"]
    )


async def test_a_genuinely_different_topology_produces_a_different_hash() -> None:
    """노드 하나가 늘거나 엣지가 다른 곳으로 이어지면 다른 그래프이므로 해시도
    달라야 한다 -- 같은 해시만 나오는 상수 구현을 잡아낸다.

    'a'/'b' 는 response_generator 가 아니므로 `mandatory=()` 로 I1 의 기본
    게이트를 명시적으로 끈다(위 두 해시 테스트와 같은 이유)."""

    bigger = GraphTopology(
        nodes=("a", "b"), edges=((START, "a"), ("a", "b"), ("b", END))
    )

    outcome_small = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_valid_topology()),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )
    outcome_bigger = await design_graph_or_fallback(
        designer=FakeGraphDesigner(bigger),
        request=_request(),
        contracts=_contracts(),
        mandatory=(),
    )

    assert (
        _accepted_event(outcome_small).payload["topology_hash"]
        != _accepted_event(outcome_bigger).payload["topology_hash"]
    )


async def test_a_topology_without_the_response_generator_is_rejected_by_default() -> (
    None
):
    """I1: `mandatory` 를 아예 넘기지 않으면 기본값이 response_generator 를
    필수로 못박는다 -- 응답을 만드는 노드가 없는 설계는 (C1 이 고친
    `initial_writes` 문제와 무관하게) 여전히 "그럴듯하지만 빈 산출물" 이므로
    `missing_mandatory` 로 거부돼야 한다. `mandatory` 인자를 생략해 기본값이
    실제로 적용되는지를 본다 -- 앞의 해시 테스트들처럼 명시적으로 끄지 않는다."""

    topology = GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))
    outcome = await design_graph_or_fallback(
        designer=FakeGraphDesigner(topology),
        request=_request(),
        contracts=_contracts(),
    )
    rejected = next(e for e in outcome.events if e.kind == "graph_design_rejected")
    assert "missing_mandatory" in {v["rule"] for v in rejected.payload["violations"]}
    assert outcome.topology is None


async def test_a_topology_with_the_response_generator_passes_the_mandatory_gate() -> (
    None
):
    """response_generator 노드가 있으면 I1 의 기본 mandatory 게이트를
    통과한다 -- `missing_mandatory` 위반이 뜨지 않는다."""

    contracts = dict(_contracts())
    contracts[WorkflowNode.RESP_GENERATOR.value] = _contract(
        WorkflowNode.RESP_GENERATOR.value
    )
    topology = GraphTopology(
        nodes=(WorkflowNode.RESP_GENERATOR.value,),
        edges=(
            (START, WorkflowNode.RESP_GENERATOR.value),
            (WorkflowNode.RESP_GENERATOR.value, END),
        ),
    )
    outcome = await design_graph_or_fallback(
        designer=FakeGraphDesigner(topology),
        request=_request(),
        contracts=contracts,
    )
    accepted = next(e for e in outcome.events if e.kind == "graph_design_accepted")
    assert accepted.payload["nodes"] == (WorkflowNode.RESP_GENERATOR.value,)


def test_topology_hash_is_public_so_static_and_designed_runs_share_one_formula() -> None:
    """설계된 run 과 정적 run 이 **같은 산식**으로 해시를 계산해야 조인이
    성립한다. 산식이 둘로 갈리면 조인은 조용히 깨진다 -- 해시는 다르기만
    하면 되므로 아무도 눈치채지 못한다."""

    from neos.workflow.graph_design_ledger import topology_hash

    topology = GraphTopology(
        nodes=("response_generator",),
        edges=(("__start__", "response_generator"), ("response_generator", "__end__")),
    )
    assert topology_hash(topology) == topology_hash(topology)
    assert len(topology_hash(topology)) == 16


def test_topology_hash_ignores_the_order_nodes_and_edges_arrived_in() -> None:
    """모델이 같은 그래프를 두 번 제안해도 JSON 순서는 그때그때 다르다.
    논리적으로 같은 설계가 다른 해시를 받으면 비교 자체가 무의미해진다."""

    from neos.workflow.graph_design_ledger import topology_hash

    forward = GraphTopology(
        nodes=("a", "b"),
        edges=(("__start__", "a"), ("a", "b"), ("b", "__end__")),
    )
    shuffled = GraphTopology(
        nodes=("b", "a"),
        edges=(("b", "__end__"), ("__start__", "a"), ("a", "b")),
    )
    assert topology_hash(forward) == topology_hash(shuffled)
