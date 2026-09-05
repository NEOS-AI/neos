import pytest


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
    # 두 노드 다 계약을 선언해야 한다 -- 계약이 없는 노드는 FIX 1(fail-closed)
    # 이후 `missing_contract` 위반이 되어 이 토폴로지가 더는 "유효"하지 않다.
    contracts = {"a": _contract("a"), "b": _contract("b")}
    topology = GraphTopology(
        nodes=("a", "b"),
        edges=((START, "a"), ("a", "b"), ("b", END)),
    )
    assert validate_topology(topology, contracts=contracts) == ()


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


def test_a_node_without_a_contract_fails_closed() -> None:
    """계약이 없는 노드는 "요구하는 게 없다" 로 통과되지 않는다 (FIX 1).

    `contracts={}` 를 넘기면 `requires` 를 아예 계산할 수 없으므로, 예전에는
    이 상태를 "이 노드는 아무것도 요구하지 않는다" 로 오인해 위반 0개로
    통과시켰다 -- `NODE_CONTRACTS` 가 `neos.workflow.graph` 를 임포트해야
    채워지는 전역 레지스트리라, 그 임포트를 빼먹은 호출자는 이 구멍으로
    아무 위반 없이 통과했다. 지금은 계약이 없는 노드 자체가 `missing_contract`
    위반이고, 어느 노드가 계약을 빠뜨렸는지 `node` 필드에 남는다.
    """
    topology = GraphTopology(
        nodes=("a",),
        edges=((START, "a"), ("a", END)),
    )
    violations = validate_topology(topology, contracts={})
    assert "missing_contract" in _rules(violations)
    assert any(v.rule == "missing_contract" and v.node == "a" for v in violations)


def test_violation_key_is_populated_only_for_key_specific_rules() -> None:
    """`TopologyViolation.key` 는 특정 `AgentState` 키에 관한 위반에서만 채워진다.

    `unsatisfied_requires` 는 어떤 키가 보장되지 않는지가 곧 위반의 정체라
    `key` 가 그 키로 채워져야 한다. 반면 `unreachable_node` 처럼 키와 무관한
    구조적 위반은 `key` 가 `None` 으로 남아야 한다 -- 예전에는 이 정보가
    한국어 `detail` 문장 안에만 있어서 회귀 테스트가 정규식으로 파싱해야
    했다.
    """
    contracts = {"integrate": _contract("integrate", requires=("search_results",))}
    topology = GraphTopology(
        nodes=("integrate", "orphan"),
        edges=((START, "integrate"), ("integrate", END)),
    )
    violations = validate_topology(topology, contracts=contracts)

    requires_violation = next(v for v in violations if v.rule == "unsatisfied_requires")
    assert requires_violation.key == "search_results"

    unreachable_violation = next(v for v in violations if v.rule == "unreachable_node")
    assert unreachable_violation.key is None


# --- must_write: I1 불변식을 노드 이름이 아니라 "쓰여야 하는 키" 로 --------------
#
# `mandatory=(response_generator,)` 는 I1("응답 없는 설계를 승인하지 않는다")을
# **특정 노드가 있어야 한다**로 적었다. 그런데 `direct_response` 도
# `final_response` 를 쓴다 -- §14.2의 G1-a 가 그 노드를 응답 생산자로 인정한
# 그대로다. 표본 `20260824T101448Z` 에서 대화형 질의 5건이 전부 거부됐고, 그
# 설계들(`[direct_response]` 등)은 **옳은 그래프**였다. 요구를 키로 적으면
# 구현 세부(어느 노드가 응답을 만드는가)와 진짜 요구(응답이 만들어지는가)가
# 갈린다.

def _writer(name: str, writes: set[str]):
    """`_ContractLike` 를 구조적으로 만족하는 최소 계약."""
    class _C:
        pass
    c = _C()
    c.writes = frozenset(writes)
    c.requires = frozenset()
    # `_ContractLike` 가 요구하는 셋째 필드. 빈 매핑이면 조건부 검사가 바로
    # 빠져나가므로 이 스텁이 겨누는 `no_writer_for_required_key` 규칙과 무관하다.
    c.requires_unless = {}
    return c


def test_a_topology_whose_only_node_writes_the_key_is_accepted() -> None:
    """`[direct_response]` 는 통과해야 한다 -- 응답을 만드는 그래프다."""

    topology = GraphTopology(
        nodes=("direct_response",),
        edges=(("__start__", "direct_response"), ("direct_response", "__end__")),
    )
    violations = validate_topology(
        topology,
        contracts={"direct_response": _writer("direct_response", {"final_response"})},
        must_write=frozenset({"final_response"}),
    )
    assert violations == ()


def test_a_topology_with_no_writer_for_the_key_is_still_refused() -> None:
    """🔴 이 테스트가 규칙 완화와 규칙 정정을 가른다.

    `[query_classifier]` 는 구조적으로 성립하지만 응답을 만들지 않는다. 그것을
    통과시키면 §14.2가 금지한 "계약을 고쳐서 위반을 없애기" 이고, I1 이 막으려던
    '그럴듯하지만 빈 산출물' 이 그대로 돌아온다."""

    topology = GraphTopology(
        nodes=("query_classifier",),
        edges=(("__start__", "query_classifier"), ("query_classifier", "__end__")),
    )
    violations = validate_topology(
        topology,
        contracts={"query_classifier": _writer("query_classifier", {"query_type"})},
        must_write=frozenset({"final_response"}),
    )
    assert [v.rule for v in violations] == ["no_writer_for_required_key"]
    assert "final_response" in violations[0].detail


def test_any_writer_satisfies_the_key_not_a_particular_node() -> None:
    """`response_generator` 로도 통과한다 -- 키를 쓰는 노드면 무엇이든 된다."""

    topology = GraphTopology(
        nodes=("response_generator",),
        edges=(("__start__", "response_generator"), ("response_generator", "__end__")),
    )
    violations = validate_topology(
        topology,
        contracts={"response_generator": _writer("response_generator", {"final_response"})},
        must_write=frozenset({"final_response"}),
    )
    assert violations == ()


# --- 조건부 요구 (`requires_unless`) -----------------------------------------
#
# G1-a 가 만든 문제다. `response_generator` 는 결과 셋(search/analysis/
# generation)을 무조건 읽지만, `final_response` 가 이미 있는 경로에서는
# `_preserve_existing_response` 로 빠져 그 셋을 읽지 않는다. 계약이 그 조건을
# 표현하지 못해 **진짜 버그와 무해한 경로가 같은 서명**을 냈고, 위반 3건이
# `_KNOWN_VIOLATIONS` 에 면제로 박혀 그 노드의 새 회귀까지 함께 가렸다.
#
# 조건이 성립하는 단위가 노드가 아니라 **진입 경로**라는 것이 핵심이다.
# `_guaranteed_keys` 는 모든 경로의 교집합이므로, 한 경로라도 면제 키를 주지
# 않으면 노드 수준에서는 면제 키가 "보장 안 됨" 이다 -- 노드 단위 면제로
# 썼다면 발동조차 하지 않았을 것이다.


def _conditional(node, *, requires_unless, reads=(), writes=()) -> NodeContract:
    return NodeContract(
        node=node,
        reads=frozenset(reads) | frozenset().union(*requires_unless.values()),
        writes=frozenset(writes),
        requires=frozenset(),
        requires_unless={k: frozenset(v) for k, v in requires_unless.items()},
        handler=lambda state: state,
    )


def test_a_conditional_requirement_is_waived_on_the_path_that_guarantees_the_waiver() -> (
    None
):
    """면제 키를 주는 경로와 요구 키를 주는 경로가 섞여 있어도 유효하다.

    `answered` 는 `final_response` 를 쓰고 `researched` 는 결과 셋을 쓴다.
    둘 다 합법인데, 노드 단위 교집합으로는 어느 쪽도 보장되지 않는다.
    """
    contracts = {
        "answered": _contract("answered", writes=("final_response",)),
        "researched": _contract("researched", writes=("search_results",)),
        "gen": _conditional(
            "gen", requires_unless={"final_response": ("search_results",)}
        ),
    }
    topology = GraphTopology(
        nodes=("answered", "researched", "gen"),
        edges=(
            (START, "answered"),
            (START, "researched"),
            ("answered", "gen"),
            ("researched", "gen"),
            ("gen", END),
        ),
    )
    assert validate_topology(topology, contracts=contracts) == ()


def test_a_conditional_requirement_fires_on_the_path_that_guarantees_neither() -> None:
    """면제 키도 요구 키도 주지 않는 경로가 하나라도 있으면 위반이다."""
    contracts = {
        "answered": _contract("answered", writes=("final_response",)),
        "empty_handed": _contract("empty_handed", writes=("unrelated",)),
        "gen": _conditional(
            "gen", requires_unless={"final_response": ("search_results",)}
        ),
    }
    topology = GraphTopology(
        nodes=("answered", "empty_handed", "gen"),
        edges=(
            (START, "answered"),
            (START, "empty_handed"),
            ("answered", "gen"),
            ("empty_handed", "gen"),
            ("gen", END),
        ),
    )
    violations = validate_topology(topology, contracts=contracts)
    assert "unsatisfied_requires" in _rules(violations)
    assert any(v.key == "search_results" for v in violations)


def test_a_conditional_violation_names_the_path_that_caused_it() -> None:
    """위반이 **어느 선행 노드**로 들어온 경로인지 이름을 댄다.

    지금 `unsatisfied_requires` 는 키 이름만 주므로, 진입 경로가 아홉인
    노드에서 어디를 고쳐야 하는지 알 수 없다. 조건부 검사는 경로별로 돌므로
    범인을 지목할 수 있고, 그 정보를 버리면 검사를 정밀하게 만든 이유가
    절반 사라진다.
    """
    contracts = {
        "answered": _contract("answered", writes=("final_response",)),
        "empty_handed": _contract("empty_handed", writes=("unrelated",)),
        "gen": _conditional(
            "gen", requires_unless={"final_response": ("search_results",)}
        ),
    }
    topology = GraphTopology(
        nodes=("answered", "empty_handed", "gen"),
        edges=(
            (START, "answered"),
            (START, "empty_handed"),
            ("answered", "gen"),
            ("empty_handed", "gen"),
            ("gen", END),
        ),
    )
    violations = validate_topology(topology, contracts=contracts)
    offenders = {v.via for v in violations if v.rule == "unsatisfied_requires"}
    assert offenders == {"empty_handed"}


def test_a_key_cannot_be_both_unconditionally_and_conditionally_required() -> None:
    """같은 키를 `requires` 와 `requires_unless` 양쪽에 적으면 모순이다.

    한쪽은 "모든 경로에서 필요" 이고 다른 쪽은 "이 경로에서는 불필요" 다.
    둘을 함께 두면 어느 쪽이 이기는지가 선언이 아니라 **검사 순서**로 정해진다.
    """
    with pytest.raises(ValueError, match="requires_unless"):
        NodeContract(
            node="gen",
            reads=frozenset({"search_results"}),
            writes=frozenset(),
            requires=frozenset({"search_results"}),
            requires_unless={"final_response": frozenset({"search_results"})},
            handler=lambda state: state,
        )
