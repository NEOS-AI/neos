"""템플릿 등록 검사(K25′ a) · 생성된 계약 · 전개 · 비용 상한."""

from dataclasses import replace

import pytest

from neos.subagent.catalog import EXPLORE, IMPLEMENT
from neos.subagent.stepper import CHILD_MAX_OUTPUT_TOKENS
from neos.workflow.subagent_nodes import (
    EXPLORE_WEB,
    SUBAGENT_NODE_TEMPLATES,
    TEMPLATE_WRITES,
    TemplateRegistrationError,
    agent_state_reducer_keys,
    expand_subagent_nodes,
    resolve_template_cost_ceiling,
    template_cost_ceiling_micros,
    validate_template,
)
from neos.workflow.topology import END, START, GraphTopology


def test_the_first_template_is_registered_and_valid() -> None:
    assert SUBAGENT_NODE_TEMPLATES == {"explore_web": EXPLORE_WEB}
    validate_template(EXPLORE_WEB)


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"tools": frozenset({"search", "spawn_agent.v1"})}, "spawn_agent.v1"),
        ({"spec": "implement", "tools": frozenset({"read_file.v1"})}, "쓰기 명세"),
        ({"tools": frozenset({"edit_file.v1"})}, "edit_file.v1"),
        ({"tools": frozenset({"web_fetch.v1"})}, "web_fetch.v1"),
        ({"spec": "nope"}, "등록돼 있지 않다"),
        ({"tools": frozenset()}, "비었다"),
        ({"briefing_from": {"scope": "original_query"}}, "'goal'"),
        ({"briefing_from": {"goal": "not_a_state_key"}}, "not_a_state_key"),
        ({"briefing_from": {"goal": "original_query", "already_tried": "errors"}}, "already_tried"),
        ({"max_turns": 9}, "max_turns"),
        ({"name": "fact_check"}, "WorkflowNode"),
        ({"label": " "}, "라벨"),
    ],
)
def test_registration_refuses_what_k25_prime_forbids(overrides, fragment) -> None:
    with pytest.raises(TemplateRegistrationError, match=fragment):
        validate_template(replace(EXPLORE_WEB, **overrides))


def test_explore_really_can_spawn_so_can_spawn_is_not_the_guard() -> None:
    # 원안은 `spec.can_spawn is False` 를 검사하려 했다. 그 검사는 이 사실 때문에
    # 모든 읽기 전용 명세를 거부한다 -- 가드는 도구 규칙이어야 한다.
    assert EXPLORE.can_spawn is True
    assert IMPLEMENT.can_spawn is False
    assert "spawn_agent.v1" not in EXPLORE_WEB.tools


def test_the_generated_contract_needs_no_hand_curation() -> None:
    contract = EXPLORE_WEB.contract()
    assert contract.node == "explore_web"
    assert contract.requires == frozenset({"original_query"})
    assert contract.reads == frozenset({"original_query", "subagent_scope", "subagent_runs"})
    assert contract.writes == TEMPLATE_WRITES
    assert not contract.hand_curated and not contract.writes_hand_curated
    # 병렬 가지에서 안전하려면 템플릿이 쓰는 키가 전부 리듀서여야 한다.
    assert TEMPLATE_WRITES <= agent_state_reducer_keys()


def test_the_placeholder_handler_refuses_to_run_as_a_static_node() -> None:
    with pytest.raises(RuntimeError, match="SubagentNodeHost"):
        EXPLORE_WEB.contract().handler(object(), {})


def test_expansion_adds_a_bounded_self_loop_and_is_idempotent() -> None:
    topology = GraphTopology(
        nodes=("explore_web", "fact_check"),
        edges=((START, "explore_web"), ("explore_web", "fact_check"), ("fact_check", END)),
    )
    expanded = expand_subagent_nodes(topology)
    assert ("explore_web", "explore_web") in expanded.edges
    assert expanded.loop_bounds == {"explore_web": 2 * EXPLORE_WEB.max_turns + 1}
    assert expand_subagent_nodes(expanded) == expanded
    plain = GraphTopology(nodes=("fact_check",), edges=((START, "fact_check"), ("fact_check", END)))
    assert expand_subagent_nodes(plain) is plain


def test_the_cost_ceiling_is_turns_times_window_input_plus_capped_output() -> None:
    ceiling = template_cost_ceiling_micros(
        EXPLORE_WEB,
        input_ceiling_tokens=1_000,
        input_micros_per_million=3_000_000,
        output_micros_per_million=15_000_000,
    )
    per_turn = 1_000 * 3_000_000 + CHILD_MAX_OUTPUT_TOKENS * 15_000_000
    assert ceiling == -(-(EXPLORE_WEB.max_turns * per_turn) // 1_000_000)


def test_the_cost_ceiling_uses_the_catalog_and_fails_closed_when_unknown() -> None:
    priced = resolve_template_cost_ceiling(
        EXPLORE_WEB, provider="anthropic", model="claude-sonnet-5"
    )
    assert priced is not None and priced > 0
    assert resolve_template_cost_ceiling(EXPLORE_WEB, provider="anthropic", model="no-such-model") is None
    assert resolve_template_cost_ceiling(EXPLORE_WEB, provider="openai", model="claude-sonnet-5") is None
