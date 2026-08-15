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


def test_an_empty_topology_is_rejected_unconditionally() -> None:
    """`mandatory` 를 넘기지 않아도(기본값 `()`) 노드 0개는 항상 위반이다.

    `{"nodes": [], "edges": []}` 는 `parse_topology` 의 형식·어휘 검사를
    통과한다 -- 빈 리스트도 유효한 타입이기 때문이다. 이 규칙이 없으면 그런
    빈 토폴로지가 여기서도 위반 0개로 승인되고, 훨씬 나중에(실제 그래프를
    빌드하는 단계에서) 정체불명의 오류로만 죽는다.
    """
    topology = GraphTopology(nodes=(), edges=())
    violations = validate_topology(topology, contracts={})
    assert "empty_topology" in _rules(violations)


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


def test_a_node_without_a_declared_cost_fails_the_budget_gate_closed() -> None:
    """예산 검사는 값을 모르는 노드를 "무료"로 봐주지 않는다 (fail closed).

    `node_costs` 에서 노드 하나가 누락돼도, 그 값을 0 으로 취급해 조용히 통과시키면
    비용이 큰 노드 하나가 실수로 빠지는 것만으로 예산 방어선이 무력화된다.
    """
    contracts = {"a": _contract("a"), "b": _contract("b")}
    topology = GraphTopology(
        nodes=("a", "b"), edges=((START, "a"), ("a", "b"), ("b", END))
    )
    violations = validate_topology(
        topology, contracts=contracts, budget=100, node_costs={"a": 1}
    )
    assert "budget_exceeded" in _rules(violations)
    assert any(v.node == "b" for v in violations)


def test_a_bypassable_loop_leaves_the_key_written_inside_it_unguaranteed() -> None:
    """루프를 건너뛰는 경로가 있으면, 루프 안에서 쓰는 키는 보장이 아니다.

    entry --(bypass)--> exit 가 entry -> body -> exit 를 건너뛸 수 있으므로,
    body 가 쓰는 키를 exit 가 requires 해도 그 경로로 들어온 실행은 빈 값을 읽는다.
    """
    contracts = {
        "entry": _contract("entry"),
        "body": _contract("body", writes=("k",)),
        "exit": _contract("exit", requires=("k",)),
    }
    topology = GraphTopology(
        nodes=("entry", "body", "exit"),
        edges=(
            (START, "entry"),
            ("entry", "body"),
            ("body", "entry"),  # 사이클: body 가 entry 로 되돌아간다
            ("body", "exit"),
            ("entry", "exit"),  # 우회: 루프(body) 를 건너뛰고 바로 exit 로
            ("exit", END),
        ),
        loop_bounds={"entry": 5, "body": 5},
    )
    violations = validate_topology(topology, contracts=contracts)
    assert "unsatisfied_requires" in _rules(violations)
    assert any(v.node == "exit" and "k" in v.detail for v in violations)


def test_a_requires_key_covered_by_initial_writes_is_satisfied_even_at_the_entry_node() -> (
    None
):
    """호출자가 START 이전에 채워 주는 키는 진입 노드에서도 보장된다.

    `entry` 는 START 에서 바로 이어지므로 어떤 노드도 거치지 않는다 -- 그런데도
    `original_query` 를 요구할 수 있는 건, 그 키가 그래프 *호출자* 의 초기 상태에
    이미 있기 때문이다(`initial_writes`).
    """
    contracts = {"entry": _contract("entry", requires=("original_query",))}
    topology = GraphTopology(
        nodes=("entry",),
        edges=((START, "entry"), ("entry", END)),
        initial_writes=frozenset({"original_query"}),
    )
    assert validate_topology(topology, contracts=contracts) == ()


def test_initial_writes_do_not_cover_keys_outside_the_declared_set() -> None:
    """`initial_writes` 는 선언된 키만 면제한다 -- 다른 키는 여전히 노드가 써야 한다."""
    contracts = {"entry": _contract("entry", requires=("search_results",))}
    topology = GraphTopology(
        nodes=("entry",),
        edges=((START, "entry"), ("entry", END)),
        initial_writes=frozenset({"original_query"}),
    )
    violations = validate_topology(topology, contracts=contracts)
    assert "unsatisfied_requires" in _rules(violations)
    assert any("search_results" in v.detail for v in violations)


def test_initial_writes_still_intersect_with_real_predecessor_guarantees() -> None:
    """START 와 실제 노드 둘 다 선행자면, 둘의 보장을 교집합해야 한다.

    `x` 는 START 직후 노드라 `k` 를 못 쓴다(`k` 는 `initial_writes` 에도 없다).
    `n` 은 `x` 와 START 양쪽에서 오므로, `x` 경로로 들어온 실행은 `k` 를 여전히
    못 받는다 -- `initial_writes` 가 비어 있는 키에 대해서까지 통과시켜서는 안 된다.
    """
    contracts = {
        "x": _contract("x", writes=("other_key",)),
        "n": _contract("n", requires=("k",)),
    }
    topology = GraphTopology(
        nodes=("x", "n"),
        edges=((START, "x"), ("x", "n"), (START, "n"), ("n", END)),
        initial_writes=frozenset({"other_key"}),
    )
    violations = validate_topology(topology, contracts=contracts)
    assert "unsatisfied_requires" in _rules(violations)
    assert any(v.node == "n" and "k" in v.detail for v in violations)


def test_an_unbypassable_loop_guarantees_the_key_written_inside_it() -> None:
    """우회 경로가 없으면, 루프 안에서 쓰는 키는 루프 뒤 노드에서 보장된다.

    위 테스트와 노드·엣지가 거의 같지만 entry -> exit 우회 엣지만 뺐다. exit 로
    가는 유일한 경로가 반드시 body 를 거치므로, body 가 쓰는 키는 반복 횟수와
    무관하게 항상 먼저 쓰여 있다 -- 보장돼야 하고, 실제로도 보장된다.
    """
    contracts = {
        "entry": _contract("entry"),
        "body": _contract("body", writes=("k",)),
        "exit": _contract("exit", requires=("k",)),
    }
    topology = GraphTopology(
        nodes=("entry", "body", "exit"),
        edges=(
            (START, "entry"),
            ("entry", "body"),
            ("body", "entry"),  # 사이클: body 가 entry 로 되돌아간다
            ("body", "exit"),  # exit 로 가는 길은 이것 하나뿐 -- 우회 없음
            ("exit", END),
        ),
        loop_bounds={"entry": 5, "body": 5},
    )
    assert validate_topology(topology, contracts=contracts) == ()
