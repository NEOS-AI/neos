import pytest

import neos.workflow.graph  # noqa: F401 -- 임포트만으로 NODE_CONTRACTS 를 채운다
from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.enums import WorkflowNode
from neos.workflow.graph_designer import (
    DesignRequest,
    FakeGraphDesigner,
    InvalidDesignPayload,
    load_graph_design_prompt,
    parse_topology,
)
from neos.workflow.topology import (
    END,
    GRAPH_ENTRY_WRITES,
    START,
    GraphTopology,
    validate_topology,
)


def test_parse_topology_accepts_a_well_formed_payload() -> None:
    topology = parse_topology(
        {"nodes": ["a", "b"], "edges": [[START, "a"], ["a", "b"], ["b", END]]},
        known_nodes=frozenset({"a", "b"}),
    )
    assert topology.nodes == ("a", "b")


def test_parse_topology_rejects_an_unknown_node() -> None:
    """서브에이전트가 없는 노드를 지어내면 여기서 막는다."""
    with pytest.raises(InvalidDesignPayload, match="unknown_node"):
        parse_topology(
            {"nodes": ["ghost"], "edges": [[START, "ghost"], ["ghost", END]]},
            known_nodes=frozenset({"a"}),
        )


def test_parse_topology_rejects_a_malformed_edge() -> None:
    with pytest.raises(InvalidDesignPayload):
        parse_topology(
            {"nodes": ["a"], "edges": [["a"]]},
            known_nodes=frozenset({"a"}),
        )


def test_parse_topology_fills_in_the_graph_entry_contract() -> None:
    """C1: `parse_topology` 는 `initial_writes` 를 `GRAPH_ENTRY_WRITES` 로
    채워야 한다 -- 이 필드가 비어 있으면 `original_query` 등을 요구하는
    진입 노드가 있는 설계가 전부 `unsatisfied_requires` 로 거부된다."""
    topology = parse_topology(
        {"nodes": ["a"], "edges": [[START, "a"], ["a", END]]},
        known_nodes=frozenset({"a"}),
    )
    assert topology.initial_writes == GRAPH_ENTRY_WRITES


def test_a_designed_topology_of_real_nodes_is_no_longer_rejected_for_original_query() -> (
    None
):
    """C1 회귀 확인: `parse_topology` 가 `initial_writes` 를 빠뜨리던 시절엔
    `query_classifier` 처럼 `original_query` 를 요구하는 자연스러운 진입
    노드가 있는 설계가 거의 전부 `unsatisfied_requires` 로 거부됐다(아홉 개
    계약이 초기 상태 키를 요구하는데, 그중 하나가 진입 노드였다). 이제는
    그 키가 START 부터 보장된 것으로 검증기에 전달돼, 이 위반이 사라져야
    한다."""

    payload = {
        "nodes": [WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value],
        "edges": [
            [START, WorkflowNode.QUERY_CLS.value],
            [WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value],
            [WorkflowNode.RESP_GENERATOR.value, END],
        ],
    }
    topology = parse_topology(payload, known_nodes=frozenset(NODE_CONTRACTS))
    violations = validate_topology(topology, contracts=NODE_CONTRACTS)

    assert not any(v.key == "original_query" for v in violations)


def test_the_prompt_file_survives_the_substitution_task_7_will_do() -> None:
    """프롬프트 파일의 출력 예시 JSON 은 str.format() 필드로 오인되면 안 된다.

    Task 7 은 이 프롬프트를
    `prompt_text.format(query_text=..., node_catalog=..., budget=...)` 로
    채울 것이다. [4]절 출력 예시의 `{"nodes": ..., "edges": ...}` 가 이중
    이스케이프돼 있지 않으면 그 호출이 `KeyError` 로 죽는다 -- 이 테스트는
    그 실제 치환을 그대로 수행해 죽지 않음을 확인한다.
    """
    prompt = load_graph_design_prompt()

    rendered = prompt.format(
        query_text="테스트 질의", node_catalog="- a: reads=x", budget=1000
    )

    assert "테스트 질의" in rendered
    assert "- a: reads=x" in rendered
    assert "1000" in rendered
    # 출력 예시의 JSON 이 이스케이프에서 살아남아 리터럴 중괄호로 남아 있어야
    # 한다 -- 사라지거나 필드로 소비되면 안 된다.
    assert '{"nodes"' in rendered


async def test_the_fake_designer_returns_what_it_was_given() -> None:
    topology = GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))
    designer = FakeGraphDesigner(topology)

    result = await designer.design(DesignRequest(query="q", catalog=(), budget=1000))

    assert result == topology
    assert designer.design_calls == 1
