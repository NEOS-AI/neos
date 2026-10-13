"""노드 반환값 → 이번 노드의 갱신 (spec 2026-10-13 §4.2, R5)."""

import numpy as np
import pytest

from neos.workflow.runtime.node_updates import (
    NodeUpdateRejected,
    apply_update,
    normalize_update,
    reducer_kinds,
    working_copy,
    wrap_node,
)
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db

A = SearchResult(source="web", title="A", content="a", url="https://a")
B = SearchResult(source="web", title="B", content="b", url="https://b")
_ALL = frozenset({"search_results", "final_response", "execution_steps", "errors", "quality_score", "x"})


def _norm(before, result, writes=_ALL, policy="raise"):
    return normalize_update("node", before, result, writes=writes, policy=policy)


def test_reducer_kinds_come_from_the_state_annotations() -> None:
    kinds = reducer_kinds()
    assert kinds["search_results"] == "append"
    assert kinds["errors"] == "append"
    assert kinds["subagent_runs"] == "merge"
    assert "final_response" not in kinds


def test_a_full_state_return_keeps_only_what_changed() -> None:
    before = {"search_results": [A], "final_response": None, "quality_score": 0.5}
    result = {**before, "final_response": "답"}
    assert _norm(before, result) == {"final_response": "답"}


def test_an_appended_full_list_becomes_the_new_items() -> None:
    before = {"search_results": [A]}
    assert _norm(before, {"search_results": [A, B]}) == {"search_results": [B]}


def test_a_delta_list_is_kept_as_is() -> None:
    before = {"search_results": [A]}
    assert _norm(before, {"search_results": [B]}) == {"search_results": [B]}


def test_an_unchanged_full_list_is_no_update() -> None:
    before = {"search_results": [A, B]}
    assert _norm(before, {"search_results": [A, B]}) == {}


def test_a_reordered_list_is_treated_as_new_items() -> None:
    """접두가 다르면 무엇이 새 것인지 모른다 -- 지금처럼 전부 붙는다(나빠지지 않는다)."""
    before = {"search_results": [A, B]}
    assert _norm(before, {"search_results": [B, A]}) == {"search_results": [B, A]}


def test_none_is_an_empty_update() -> None:
    assert _norm({"x": 1}, None) == {}


def test_runtime_keys_are_never_updates() -> None:
    assert _norm({}, {"_event_handler": object(), "x": 1}) == {"x": 1}


def test_values_whose_equality_raises_count_as_changed() -> None:
    before = {"x": np.array([1, 2])}
    result = {"x": np.array([1, 2])}
    assert "x" in _norm(before, result)


def test_in_place_mutation_becomes_an_update() -> None:
    before = {"execution_steps": [{"step": 1}]}

    async def node(state):
        state["execution_steps"].append({"step": 2})
        return state

    import asyncio

    update = asyncio.run(wrap_node("node", node, policy="raise")(before))
    assert update == {"execution_steps": [{"step": 1}, {"step": 2}]}
    assert before == {"execution_steps": [{"step": 1}]}


def test_raise_policy_rejects_keys_outside_writes() -> None:
    with pytest.raises(NodeUpdateRejected) as error:
        _norm({}, {"x": 1, "final_response": "답"}, writes=frozenset({"x"}))
    assert error.value.keys == ("final_response",)


def test_drop_policy_removes_keys_outside_writes() -> None:
    assert _norm({}, {"x": 1, "final_response": "답"}, writes=frozenset({"x"}), policy="drop") == {"x": 1}


def test_report_policy_keeps_keys_outside_writes() -> None:
    update = _norm({}, {"x": 1, "final_response": "답"}, writes=frozenset({"x"}), policy="report")
    assert update == {"x": 1, "final_response": "답"}


def test_unchanged_keys_outside_writes_are_not_violations() -> None:
    """전체 상태를 돌려주는 노드가 건드리지 않은 키로 위반이 되면 안 된다."""
    before = {"x": 1, "final_response": "답"}
    assert _norm(before, {**before, "x": 2}, writes=frozenset({"x"})) == {"x": 2}


def test_working_copy_isolates_lists_and_dicts() -> None:
    state = {"l": [1], "d": {"k": 1}, "o": object()}
    copy = working_copy(state)
    copy["l"].append(2)
    copy["d"]["k2"] = 2
    assert state == {"l": [1], "d": {"k": 1}, "o": state["o"]}
    assert copy["o"] is state["o"]


def test_apply_update_appends_merges_and_replaces() -> None:
    state = {"search_results": [A], "subagent_runs": {"a": 1}, "final_response": "옛"}
    merged = apply_update(state, {"search_results": [B], "subagent_runs": {"b": 2}, "final_response": "새"})
    assert merged == {"search_results": [A, B], "subagent_runs": {"a": 1, "b": 2}, "final_response": "새"}


def test_apply_update_does_not_mutate_the_input_state() -> None:
    state = {"search_results": [A], "subagent_runs": {"a": 1}}
    apply_update(state, {"search_results": [B], "subagent_runs": {"b": 2}})
    assert state == {"search_results": [A], "subagent_runs": {"a": 1}}
