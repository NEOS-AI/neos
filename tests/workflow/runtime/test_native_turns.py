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


_UNDECODABLE = '{"x": {"__t": "dc", "c": "Gone", "v": {}}}'


def _plant_undecodable(sessions, session_id):
    sessions._rows[session_id] = ("u1", _UNDECODABLE, 1, datetime.now(UTC))


async def test_an_undecodable_session_starts_fresh(monkeypatch) -> None:
    seen: list[list] = []

    def direct(state):
        seen.append(list(state["search_results"]))
        return {"search_results": [A] if len(seen) == 1 else [B]}

    workflow = stub_workflow(monkeypatch, _plan(direct), runtime="native")
    sessions, _ = workflow.native_stores
    _plant_undecodable(sessions, "s-bad")
    first = await workflow.execute_workflow(user_input(session_id="s-bad"), event_handler=RecordingHandler())
    second = await workflow.execute_workflow(user_input(session_id="s-bad"), event_handler=RecordingHandler())
    assert first["success"] is True and second["success"] is True
    # 읽지 못한 행은 지워졌다 -- 첫 턴의 저장이 이기고 두 번째 턴이 그것을 이어받는다.
    assert seen == [[], [A]]
    assert (await sessions.load("s-bad")).state["search_results"] == [A, B]


async def test_a_gate_on_a_previously_undecodable_session_still_waits(monkeypatch) -> None:
    pending = [{"request_id": "apr_bad", "skill_name": "x"}]
    plan = StubPlan(
        nodes={N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": pending, "approval_decision": None}},
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval"},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    sessions, lifecycle = workflow.native_stores
    _plant_undecodable(sessions, "s-bad-gate")
    result = await workflow.execute_workflow(user_input(session_id="s-bad-gate"), event_handler=RecordingHandler())
    assert result.get("interrupted") is True
    assert result["success"] is True
    record = await lifecycle.store.waiting_for_session("s-bad-gate")
    assert record.pending["request_ids"] == ["apr_bad"]
    assert (await sessions.load("s-bad-gate")).state["pending_approvals"] == pending


async def test_a_work_ledger_failure_keeps_the_answer(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _plan(lambda s: {}), runtime="native")
    _, lifecycle = workflow.native_stores

    async def down(*args, **kwargs):
        raise RuntimeError("work store down")

    monkeypatch.setattr(lifecycle, "complete", down)
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(session_id="s-ledger"), event_handler=handler)
    assert result["success"] is True
    assert result["response"] == "답"


async def test_a_parallel_design_falls_back_to_static_on_native(monkeypatch) -> None:
    """네이티브 러너는 순차만 돈다 -- `_resolve_execution_graph` 가 병렬 설계를 거절해 정적으로 폴백한다."""
    from neos.config.settings import settings
    from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

    # 병렬 금지만 빼면 유효한 설계다 -- 다른 위반으로 폴백하면 이 시험은 배선을 고정하지 못한다.
    chain = (N.QUERY_CLS.value, N.SEARCH_ORCHESTRATOR.value, N.DIRECT_RESPONSE.value)
    fanout = GraphTopology(
        nodes=chain,
        edges=((START, chain[0]), (chain[0], chain[1]), (chain[0], chain[2]), (chain[1], END), (chain[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    class Designer:
        async def design(self, request):
            return fanout

    workflow = stub_workflow(monkeypatch, _plan(lambda s: {}), runtime="native")
    monkeypatch.setattr(settings.config.workflow, "graph_design_enabled", True)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: Designer())
    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "q", "session_id": "s-fanout"}, use_checkpointer=False, span=None
    )
    assert resolved.source == "static"
    assert resolved.runner is not None
