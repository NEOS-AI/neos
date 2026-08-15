import pytest

from neos.workflow.graph_designer import (
    DesignRequest,
    FakeGraphDesigner,
    InvalidDesignPayload,
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


async def test_the_fake_designer_returns_what_it_was_given() -> None:
    topology = GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))
    designer = FakeGraphDesigner(topology)

    result = await designer.design(DesignRequest(query="q", catalog=(), budget=1000))

    assert result == topology
    assert designer.design_calls == 1
