from neos.workflow.topology import (
    END,
    START,
    GraphTopology,
    validate_topology,
)


def _rules(violations) -> set[str]:
    return {v.rule for v in violations}


def test_a_linear_topology_is_valid() -> None:
    topology = GraphTopology(
        nodes=("a", "b"),
        edges=((START, "a"), ("a", "b"), ("b", END)),
    )
    assert validate_topology(topology, contracts={}) == ()


def test_an_unreachable_node_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a", "orphan"),
        edges=((START, "a"), ("a", END)),
    )
    violations = validate_topology(topology, contracts={})
    assert "unreachable_node" in _rules(violations)
    assert any(v.node == "orphan" for v in violations)


def test_a_node_that_cannot_reach_end_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a", "sink"),
        edges=((START, "a"), ("a", "sink")),
    )
    assert "dead_end" in _rules(validate_topology(topology, contracts={}))


def test_an_unbounded_cycle_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a", "b"),
        edges=((START, "a"), ("a", "b"), ("b", "a"), ("b", END)),
    )
    assert "unbounded_cycle" in _rules(validate_topology(topology, contracts={}))


def test_an_edge_to_an_undeclared_node_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a",),
        edges=((START, "a"), ("a", "ghost"), ("a", END)),
    )
    assert "unknown_node" in _rules(validate_topology(topology, contracts={}))
