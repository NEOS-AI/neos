"""트랙 I 템플릿 규칙 셋 -- 무는지 변이로 확인한다 (로드맵 §10).

규칙마다 "통과해야 할 토폴로지" 와 "거부돼야 할 토폴로지" 를 쌍으로 둔다. 한쪽만
있으면 항상 통과하는(또는 항상 거부하는) 규칙도 초록이다.

그리고 **플래그가 꺼진 세계가 그대로인지**를 고정한다: 기존 31개 계약과 정적
토폴로지의 검증 결과가 `subagent` 인자의 유무·템플릿 부재에 따라 바뀌지 않는다.
"""

import pytest

import neos.workflow.graph  # noqa: F401 -- NODE_CONTRACTS 를 채운다
from neos.workflow.contracts import NODE_CONTRACTS, NodeContract
from neos.workflow.subagent_nodes import (
    EXPLORE_WEB,
    SUBAGENT_NODE_TEMPLATES,
    agent_state_reducer_keys,
    build_rule_inputs,
    expand_subagent_nodes,
    merged_contracts,
)
from neos.workflow.topology import (
    END,
    GRAPH_ENTRY_WRITES,
    START,
    GraphTopology,
    SubagentRuleInputs,
    validate_topology,
)
from neos.workflow.topology_export import static_topology

S = EXPLORE_WEB.name


def _contract(node, *, writes=(), requires=()) -> NodeContract:
    return NodeContract(
        node=node,
        reads=frozenset(requires),
        writes=frozenset(writes),
        requires=frozenset(requires),
        handler=lambda state: state,
    )


def _inputs(*, budget=10_000, ceiling=100, reducers=frozenset()) -> SubagentRuleInputs:
    return SubagentRuleInputs(
        template_nodes=frozenset({S}),
        check_nodes=frozenset({"fact_check"}),
        reducer_keys=frozenset({"search_results", "subagent_runs", "subagent_reports"})
        | reducers,
        cost_ceilings_micros={S: ceiling},
        budget_micros=budget,
    )


def _contracts(**extra) -> dict:
    base = {
        S: EXPLORE_WEB.contract(),
        "fact_check": _contract("fact_check", writes={"fact_check_result"}),
        "respond": _contract("respond", writes={"final_response"}),
    }
    base.update(extra)
    return base


def _topology(nodes, edges) -> GraphTopology:
    return expand_subagent_nodes(
        GraphTopology(nodes=tuple(nodes), edges=tuple(edges), initial_writes=GRAPH_ENTRY_WRITES)
    )


def _rules(violations) -> set[str]:
    return {v.rule for v in violations}


_CHECKED = _topology(
    (S, "fact_check", "respond"),
    ((START, S), (S, "fact_check"), ("fact_check", "respond"), ("respond", END)),
)


def test_a_checked_template_topology_is_valid() -> None:
    assert validate_topology(_CHECKED, contracts=_contracts(), subagent=_inputs()) == ()


# -- unchecked_subagent_report ----------------------------------------------


def test_a_report_path_that_skips_the_check_is_rejected() -> None:
    topology = _topology(
        (S, "respond"), ((START, S), (S, "respond"), ("respond", END))
    )
    violations = validate_topology(topology, contracts=_contracts(), subagent=_inputs())
    assert _rules(violations) == {"unchecked_subagent_report"}


def test_one_unchecked_branch_is_enough_to_reject() -> None:
    topology = _topology(
        (S, "fact_check", "respond"),
        (
            (START, S),
            (S, "fact_check"),
            (S, "respond"),
            ("fact_check", "respond"),
            ("respond", END),
        ),
    )
    violations = validate_topology(topology, contracts=_contracts(), subagent=_inputs())
    assert "unchecked_subagent_report" in _rules(violations)


def test_quality_validator_does_not_count_as_a_check() -> None:
    topology = _topology(
        (S, "quality_validator", "respond"),
        ((START, S), (S, "quality_validator"), ("quality_validator", "respond"), ("respond", END)),
    )
    contracts = _contracts(quality_validator=_contract("quality_validator"))
    violations = validate_topology(topology, contracts=contracts, subagent=_inputs())
    assert "unchecked_subagent_report" in _rules(violations)


# -- subagent_budget_exceeded ------------------------------------------------


def test_a_template_within_budget_passes_and_over_budget_is_rejected() -> None:
    ok = validate_topology(_CHECKED, contracts=_contracts(), subagent=_inputs(budget=100, ceiling=100))
    over = validate_topology(_CHECKED, contracts=_contracts(), subagent=_inputs(budget=99, ceiling=100))
    assert ok == ()
    assert _rules(over) == {"subagent_budget_exceeded"}


def test_an_unpriced_template_fails_closed() -> None:
    violations = validate_topology(
        _CHECKED, contracts=_contracts(), subagent=_inputs(ceiling=None)
    )
    assert _rules(violations) == {"subagent_budget_exceeded"}
    assert any(v.node == S for v in violations)


def test_a_missing_budget_fails_closed() -> None:
    violations = validate_topology(
        _CHECKED, contracts=_contracts(), subagent=_inputs(budget=None)
    )
    assert _rules(violations) == {"subagent_budget_exceeded"}


# -- concurrent_write_conflict -----------------------------------------------


_PARALLEL_EDGES = (
    (START, "a"),
    ("a", S),
    ("a", "b"),
    (S, "fact_check"),
    ("b", "fact_check"),
    ("fact_check", "respond"),
    ("respond", END),
)


def test_parallel_branches_writing_only_reducer_keys_pass() -> None:
    contracts = _contracts(
        a=_contract("a"), b=_contract("b", writes={"search_results"})
    )
    topology = _topology(("a", S, "b", "fact_check", "respond"), _PARALLEL_EDGES)
    assert validate_topology(topology, contracts=contracts, subagent=_inputs()) == ()


def test_parallel_branches_writing_a_plain_key_are_rejected() -> None:
    contracts = _contracts(
        a=_contract("a"),
        b=_contract("b", writes={"subagent_reports"}),
    )
    topology = _topology(("a", S, "b", "fact_check", "respond"), _PARALLEL_EDGES)
    # 같은 모양, 리듀서 집합에서 subagent_reports 만 뺀다 -- 변이는 이것 하나다.
    inputs = SubagentRuleInputs(
        template_nodes=frozenset({S}),
        check_nodes=frozenset({"fact_check"}),
        reducer_keys=frozenset({"search_results", "subagent_runs"}),
        cost_ceilings_micros={S: 1},
        budget_micros=10,
    )
    violations = validate_topology(topology, contracts=contracts, subagent=inputs)
    conflicts = [v for v in violations if v.rule == "concurrent_write_conflict"]
    assert [(v.key, {v.node, v.via}) for v in conflicts] == [
        ("subagent_reports", {S, "b"})
    ]


def test_sequential_nodes_writing_the_same_plain_key_do_not_conflict() -> None:
    contracts = _contracts(
        a=_contract("a", writes={"execution_steps"}),
        fact_check=_contract("fact_check", writes={"execution_steps"}),
    )
    topology = _topology(
        ("a", S, "fact_check", "respond"),
        ((START, "a"), ("a", S), (S, "fact_check"), ("fact_check", "respond"), ("respond", END)),
    )
    assert validate_topology(topology, contracts=contracts, subagent=_inputs()) == ()


# -- 걸음 상한이 사이클 규칙에 보인다 --------------------------------------------


def test_the_expanded_self_loop_is_bounded_and_the_raw_one_is_not() -> None:
    raw = GraphTopology(
        nodes=(S, "fact_check", "respond"),
        edges=((START, S), (S, S), (S, "fact_check"), ("fact_check", "respond"), ("respond", END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    assert "unbounded_cycle" in _rules(
        validate_topology(raw, contracts=_contracts(), subagent=_inputs())
    )
    assert validate_topology(
        expand_subagent_nodes(raw), contracts=_contracts(), subagent=_inputs()
    ) == ()


# -- 플래그 off 불변 ----------------------------------------------------------


def test_the_registered_static_contracts_are_still_exactly_31_and_template_free() -> None:
    assert len(NODE_CONTRACTS) == 31
    assert not set(NODE_CONTRACTS) & set(SUBAGENT_NODE_TEMPLATES)


def test_the_static_topology_verdict_is_unchanged_by_the_subagent_argument() -> None:
    topology = static_topology()
    baseline = validate_topology(topology, contracts=NODE_CONTRACTS)
    assert validate_topology(topology, contracts=NODE_CONTRACTS, subagent=None) == baseline
    inputs = build_rule_inputs(
        provider="anthropic", budget_micros=1, model_for_role=lambda p, r: "claude-sonnet-5"
    )
    assert (
        validate_topology(
            topology, contracts=merged_contracts(NODE_CONTRACTS), subagent=inputs
        )
        == baseline
    )


@pytest.mark.parametrize(
    "edges",
    [
        # 템플릿 없는 설계 -- 병렬 가지가 리듀서 없는 키를 같이 써도 새 규칙은 돌지 않는다
        ((START, "a"), (START, "b"), ("a", "respond"), ("b", "respond"), ("respond", END)),
    ],
)
def test_template_free_designs_are_judged_as_before(edges) -> None:
    contracts = _contracts(
        a=_contract("a", writes={"execution_steps"}),
        b=_contract("b", writes={"execution_steps"}),
    )
    topology = GraphTopology(nodes=("a", "b", "respond"), edges=edges)
    assert validate_topology(topology, contracts=contracts, subagent=_inputs()) == (
        validate_topology(topology, contracts=contracts)
    )


def test_reducer_keys_come_from_agent_state_annotations() -> None:
    keys = agent_state_reducer_keys()
    assert {"search_results", "subagent_runs", "subagent_reports", "errors"} <= keys
    assert "execution_steps" not in keys
    assert "final_response" not in keys
