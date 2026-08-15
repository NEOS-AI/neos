from neos.workflow.contracts import NodeContract
from neos.workflow.topology import (
    END,
    START,
    GraphTopology,
    validate_topology,
)


def _rules(violations) -> set[str]:
    return {v.rule for v in violations}


def _contract(node, *, reads=(), writes=(), requires=()) -> NodeContract:
    return NodeContract(
        node=node,
        reads=frozenset(reads) | frozenset(requires),
        writes=frozenset(writes),
        requires=frozenset(requires),
        handler=lambda state: state,
    )


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


def test_a_requires_key_written_upstream_is_satisfied() -> None:
    contracts = {
        "search": _contract("search", writes=("search_results",)),
        "integrate": _contract("integrate", requires=("search_results",)),
    }
    topology = GraphTopology(
        nodes=("search", "integrate"),
        edges=((START, "search"), ("search", "integrate"), ("integrate", END)),
    )
    assert validate_topology(topology, contracts=contracts) == ()


def test_a_requires_key_never_written_is_rejected() -> None:
    contracts = {"integrate": _contract("integrate", requires=("search_results",))}
    topology = GraphTopology(
        nodes=("integrate",),
        edges=((START, "integrate"), ("integrate", END)),
    )
    violations = validate_topology(topology, contracts=contracts)
    assert "unsatisfied_requires" in _rules(violations)
    assert any("search_results" in v.detail for v in violations)


def test_a_key_written_on_only_one_branch_is_rejected() -> None:
    """분기 하나에만 있으면, 다른 분기로 들어온 실행은 빈 값을 읽는다.

    이것이 이 검증기의 존재 이유다 -- 예외가 나지 않고 조용히 빈 산출물이 나온다.
    """
    contracts = {
        "search": _contract("search", writes=("search_results",)),
        "skip": _contract("skip"),
        "integrate": _contract("integrate", requires=("search_results",)),
    }
    topology = GraphTopology(
        nodes=("search", "skip", "integrate"),
        edges=(
            (START, "search"),
            (START, "skip"),
            ("search", "integrate"),
            ("skip", "integrate"),
            ("integrate", END),
        ),
    )
    assert "unsatisfied_requires" in _rules(
        validate_topology(topology, contracts=contracts)
    )


def test_a_missing_mandatory_node_is_rejected() -> None:
    topology = GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))
    violations = validate_topology(
        topology, contracts={}, mandatory=("resp_generator",)
    )
    assert "missing_mandatory" in _rules(violations)


def test_a_topology_over_budget_is_rejected() -> None:
    contracts = {"a": _contract("a"), "b": _contract("b")}
    topology = GraphTopology(
        nodes=("a", "b"), edges=((START, "a"), ("a", "b"), ("b", END))
    )
    violations = validate_topology(
        topology, contracts=contracts, budget=1, node_costs={"a": 1, "b": 1}
    )
    assert "budget_exceeded" in _rules(violations)
