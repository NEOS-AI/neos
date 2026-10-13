"""네이티브 턴 (spec 2026-10-13 §4.3·§4.4): 상태 이어받기 · 작업 기록 · 승인 대기 저장."""

from datetime import UTC, datetime

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.state import SearchResult
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

A = SearchResult(source="web", title="A", content="a", url="https://a")
B = SearchResult(source="web", title="B", content="b", url="https://b")


def _answer(text):
    return lambda state: {"final_response": text, "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}


def _plan(direct, answer="답"):
    return StubPlan(
        nodes={N.DIRECT_RESPONSE.value: direct, N.RESP_GENERATOR.value: _answer(answer)},
        routes=SKIP_PATH_ROUTES,
    )


async def test_the_second_turn_carries_accumulated_state_and_resets_turn_fields(monkeypatch) -> None:
    seen: list[dict] = []

    def direct(state):
        seen.append({"search_results": list(state["search_results"]), "skill_sources": state.get("skill_sources")})
        return {"search_results": [A] if len(seen) == 1 else [B], "skill_sources": [A] if len(seen) == 1 else None}

    workflow = stub_workflow(monkeypatch, _plan(direct), runtime="native")
    first = await workflow.execute_workflow(user_input(session_id="s-carry"), event_handler=RecordingHandler())
    second = await workflow.execute_workflow(user_input(session_id="s-carry"), event_handler=RecordingHandler())
    assert first["success"] and second["success"]
    assert seen[1]["search_results"] == [A]  # 이어받았다
    assert seen[1]["skill_sources"] is None  # 턴 리셋 필드
    sessions, _ = workflow.native_stores
    assert (await sessions.load("s-carry")).state["search_results"] == [A, B]


async def test_a_turn_records_its_work(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _plan(lambda s: {}), runtime="native")
    result = await workflow.execute_workflow(user_input(session_id="s-work"), event_handler=RecordingHandler())
    _, lifecycle = workflow.native_stores
    record = await lifecycle.store.get(result["work_id"])
    assert record.status == "completed"
    assert record.result["final_response"] == "답"
    assert record.entry == "web" and record.session_id == "s-work"


async def test_a_failing_turn_marks_the_work_failed(monkeypatch) -> None:
    def boom(state):
        raise RuntimeError("노드 실패")

    workflow = stub_workflow(monkeypatch, _plan(boom), runtime="native")
    result = await workflow.execute_workflow(user_input(session_id="s-fail"), event_handler=RecordingHandler())
    assert result["success"] is False
    _, lifecycle = workflow.native_stores
    failed = [r for r in lifecycle.store._rows.values() if r.session_id == "s-fail"]
    assert [r.status for r in failed] == ["failed"]


async def test_an_approval_gate_saves_and_waits(monkeypatch) -> None:
    pending = [{"request_id": "apr_1", "skill_name": "x"}]
    plan = StubPlan(
        nodes={N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": pending, "approval_decision": None}},
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval"},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(session_id="s-gate"), event_handler=handler)
    assert result["interrupted"] is True
    assert result["pending_approvals"] == pending
    assert handler.approvals == [pending]
    sessions, lifecycle = workflow.native_stores
    record = await lifecycle.store.waiting_for_session("s-gate")
    assert record.pending["next_node"] == N.EXECUTION_APPROVAL.value
    assert record.pending["request_ids"] == ["apr_1"]
    assert (await sessions.load("s-gate")).state["pending_approvals"] == pending


async def test_a_stateless_turn_does_not_interrupt(monkeypatch) -> None:
    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": [{"request_id": "r"}], "approval_decision": None},
            N.RESP_GENERATOR.value: _answer("통과"),
        },
        routes={
            **SKIP_PATH_ROUTES,
            "_route_after_skill_tool_selector": "needs_approval",
            "_should_continue_after_approval": "rejected",
        },
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    result = await workflow.execute_workflow(user_input(session_id="s-stateless"), event_handler=RecordingHandler(), use_checkpointer=False)
    assert result.get("interrupted") is not True
    assert result["response"] == "통과"
    sessions, _ = workflow.native_stores
    assert await sessions.load("s-stateless") is None


async def test_an_undecodable_session_starts_fresh(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _plan(lambda s: {}), runtime="native")
    sessions, _ = workflow.native_stores
    sessions._rows["s-bad"] = ("u1", '{"x": {"__t": "dc", "c": "Gone", "v": {}}}', 1, datetime.now(UTC))
    result = await workflow.execute_workflow(user_input(session_id="s-bad"), event_handler=RecordingHandler())
    assert result["success"] is True


async def test_a_parallel_design_falls_back_to_static_on_native(monkeypatch) -> None:
    from neos.workflow.contracts import NODE_CONTRACTS
    from neos.workflow.graph_design_ledger import design_graph_or_fallback
    from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

    chain = (N.QUERY_CLS.value, N.SEARCH_ORCHESTRATOR.value, N.RESP_GENERATOR.value)
    fanout = GraphTopology(
        nodes=chain,
        edges=((START, chain[0]), (chain[0], chain[1]), (chain[0], chain[2]), (chain[1], END), (chain[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    class Designer:
        async def design(self, request):
            return fanout

    from neos.workflow.graph_designer import DesignRequest

    outcome = await design_graph_or_fallback(
        designer=Designer(),
        request=DesignRequest(query="q", catalog=tuple(NODE_CONTRACTS.values()), budget=None),
        contracts=NODE_CONTRACTS,
        allow_parallel=False,
    )
    assert outcome.topology is None
