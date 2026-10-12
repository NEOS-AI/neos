"""배선 (spec §2). 소스에서 뽑은 정적 토폴로지로 본다 -- 그래프를 인스턴스화하지 않는다."""

from unittest.mock import AsyncMock

import pytest

import neos.workflow.graph as graph_module
from neos.workflow.enums import WorkflowNode
from neos.workflow.execution_graph import current_static_flags
from neos.workflow.state import SearchResult
from neos.workflow.topology_export import static_topology

pytestmark = pytest.mark.no_db

EX = WorkflowNode.SKILL_EXECUTOR.value
SEL = WorkflowNode.SKILL_TOOL_SELECTOR.value
DIRECT = WorkflowNode.DIRECT_RESPONSE.value
HYP = WorkflowNode.HYPOTHESIS_GENERATION.value
APPROVAL = WorkflowNode.EXECUTION_APPROVAL.value
RESP = WorkflowNode.RESP_GENERATOR.value

_DEEP_OFF = {"recursive": False, "hyper_deep": False, "deep_analysis": False, "execution_approval": False, "a2ui": False}


def _edges(**flags) -> set[tuple[str, str]]:
    return set(static_topology(flags=flags).edges)


def test_flag_off_keeps_the_original_wiring() -> None:
    topology = static_topology(flags={"skill_execution": False})
    edges = set(topology.edges)
    assert EX not in topology.nodes
    assert {(SEL, DIRECT), (SEL, HYP), (APPROVAL, HYP), (APPROVAL, RESP)} <= edges


def test_skip_use_and_approved_go_through_the_executor() -> None:
    edges = _edges(skill_execution=True)
    assert (SEL, EX) in edges and (APPROVAL, EX) in edges
    assert (SEL, DIRECT) not in edges and (SEL, HYP) not in edges and (APPROVAL, HYP) not in edges
    assert {target for source, target in edges if source == EX} == {DIRECT, HYP}


def test_the_else_branch_is_wired_the_same_way() -> None:
    edges = _edges(skill_execution=True, **_DEEP_OFF)
    assert (SEL, EX) in edges and (SEL, DIRECT) not in edges and (SEL, HYP) not in edges


def test_rejection_never_reaches_the_executor() -> None:
    edges = _edges(skill_execution=True)
    assert (APPROVAL, RESP) in edges
    assert {source for source, target in edges if target == EX} == {SEL, APPROVAL}


def test_deep_and_short_circuit_paths_bypass_the_executor() -> None:
    edges = _edges(skill_execution=True)
    for target in (
        WorkflowNode.MISSION_PLANNER.value,
        WorkflowNode.HYPER_DEEP_ORCHESTRATOR.value,
        WorkflowNode.RECURSIVE_ORCHESTRATOR.value,
        WorkflowNode.DEEP_ANALYSIS_DISPATCH.value,
        WorkflowNode.TASK_SCHEDULING_NODE.value,
        APPROVAL,
    ):
        assert (SEL, target) in edges, target


def test_the_runtime_flag_reaches_the_topology_flags(monkeypatch) -> None:
    monkeypatch.setattr(graph_module.settings, "SKILL_EXECUTION_ENABLED", True)
    assert current_static_flags()["skill_execution"] is True


# -- 노드 본체 ---------------------------------------------------------------


def _node():
    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    return workflow._skill_executor_node


async def test_the_node_is_a_no_op_when_the_flag_is_off(monkeypatch) -> None:
    monkeypatch.setattr(graph_module.settings, "SKILL_EXECUTION_ENABLED", False)
    assert await _node()({"skill_calls": [{"name": "arxiv", "params": {"query": "q"}}]}) == {}


async def test_the_node_runs_once_per_turn(monkeypatch) -> None:
    monkeypatch.setattr(graph_module.settings, "SKILL_EXECUTION_ENABLED", True)
    assert await _node()({"skill_calls": [{"name": "arxiv"}], "skill_execution_done": True}) == {}
    assert await _node()({"skill_calls": []}) == {"skill_execution_done": True}


async def test_the_node_writes_results_and_steps(monkeypatch) -> None:
    import neos.skills.executor as executor_module
    from neos.skills.executor import SkillExecutionOutcome, SkillStep

    monkeypatch.setattr(graph_module.settings, "SKILL_EXECUTION_ENABLED", True)
    result = SearchResult(source="arxiv", title="t", content="c")
    fake = AsyncMock(return_value=SkillExecutionOutcome(results=(result,), steps=(SkillStep("arxiv", "ok", "ok", 3, 1),)))
    monkeypatch.setattr(executor_module, "execute_skill_calls", fake)
    calls = [{"name": "arxiv", "params": {"query": "q"}, "reason": ""}]

    update = await _node()({"skill_calls": calls, "execution_steps": [{"step": "before"}]})

    assert update["search_results"] == [result]
    assert update["skill_sources"] == [result]
    assert update["skill_execution_done"] is True
    assert [s["step"] for s in update["execution_steps"]] == ["before", "skill_execution"]
    assert fake.await_args.args[0] == calls
    limits = fake.await_args.kwargs["limits"]
    assert (limits.timeout_seconds, limits.max_results_per_skill, limits.max_content_chars) == (15.0, 5, 4000)


def test_initial_state_resets_the_per_turn_skill_and_approval_fields() -> None:
    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    state = workflow._create_initial_state({"user_id": "u", "session_id": "s", "query": "q"})
    assert "skill_calls" in state and "skill_execution_done" in state and "approval_outcome" in state
    assert state["skill_calls"] is None
    assert state["skill_execution_done"] is None
    assert "skill_sources" in state and state["skill_sources"] is None
    assert state["approval_outcome"] is None


def test_approval_router_treats_a_reset_outcome_as_rejected() -> None:
    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    assert workflow._should_continue_after_approval({"approval_outcome": None}) == "rejected"
    assert workflow._should_continue_after_approval({}) == "rejected"
    assert workflow._should_continue_after_approval({"approval_outcome": "approved"}) == "approved"
