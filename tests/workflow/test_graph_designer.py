import pytest

from neos.workflow.graph_designer import (
    DesignRequest,
    FakeGraphDesigner,
    InvalidDesignPayload,
    load_graph_design_prompt,
    parse_topology,
)
from neos.workflow.topology import END, START, GraphTopology


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
