"""승인 서비스 (spec 2026-10-13 §4.5). 그래프가 아니라 작업 행을 읽는다."""

import asyncio
from dataclasses import replace

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.runtime.approvals import Refusal, ResumeTicket, WorkflowApprovals
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

PENDING = [{"request_id": "apr_1", "skill_name": "x"}]
AFTER = {"_should_continue_after_approval": "approved", "_should_replan": "skip_replan", "_should_regenerate": "proceed"}


async def _waiting(monkeypatch, session_id="s-appr", reached=None):
    reached = reached if reached is not None else []

    def answer(state):
        reached.append(state.get("approval_decision"))
        return {"final_response": "승인 후 답", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": PENDING, "approval_decision": None},
            N.RESP_GENERATOR.value: answer,
        },
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval", **AFTER},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    await workflow.execute_workflow(user_input(session_id=session_id), event_handler=RecordingHandler())
    _, lifecycle = workflow.native_stores
    return workflow, WorkflowApprovals(workflow, lifecycle), reached


async def test_pending_for_session_reads_the_work_row(monkeypatch) -> None:
    _, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    assert pending.user_id == "u1"
    assert pending.request_ids == ("apr_1",)


async def test_decide_then_resume_runs_from_the_gate_with_the_decision(monkeypatch) -> None:
    _, approvals, reached = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    ticket = await approvals.decide(pending.work_id, "apr_1", "approved", actor="u1")
    assert isinstance(ticket, ResumeTicket)
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is True
    assert result["response"] == "승인 후 답"
    assert reached == ["approved"]
    assert await approvals.pending_for_session("s-appr") is None


async def test_refusals(monkeypatch) -> None:
    _, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    assert await approvals.decide(pending.work_id, "apr_x", "approved", actor="u1") == Refusal("unknown_request")
    assert await approvals.decide(pending.work_id, "apr_1", "approved", actor="intruder") == Refusal("not_owner")
    assert await approvals.decide("wk_missing", "apr_1", "approved", actor="u1") == Refusal("expired")


async def test_two_concurrent_decisions_resume_once(monkeypatch) -> None:
    _, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    first, second = await asyncio.gather(
        approvals.decide(pending.work_id, "apr_1", "approved", actor="u1"),
        approvals.decide(pending.work_id, "apr_1", "rejected", actor="u1"),
    )
    outcomes = sorted([type(first).__name__, type(second).__name__])
    assert outcomes == ["Refusal", "ResumeTicket"]


async def test_expire_closes_the_wait_without_resuming(monkeypatch) -> None:
    workflow, approvals, reached = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    assert await approvals.expire("s-appr", "apr_1") is True
    assert await approvals.pending_for_session("s-appr") is None
    assert reached == []
    _, lifecycle = workflow.native_stores
    assert (await lifecycle.store.get(pending.work_id)).status == "expired"


async def test_resume_without_a_session_fails_the_work(monkeypatch) -> None:
    workflow, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    ticket = await approvals.decide(pending.work_id, "apr_1", "approved", actor="u1")
    sessions, lifecycle = workflow.native_stores
    await sessions.reset("s-appr")
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is False
    assert (await lifecycle.store.get(pending.work_id)).status == "failed"


async def test_a_resumed_turn_records_its_episode_with_the_original_query(monkeypatch) -> None:
    """멈춘 앞 절반은 에피소드를 남기지 않는다 -- 재개 턴이 실제 질문으로 남겨야 한다."""
    workflow, approvals, _ = await _waiting(monkeypatch)
    recorded: list[dict] = []

    async def _record(user_input, result, final_state):
        recorded.append(dict(user_input))

    monkeypatch.setattr(workflow, "_save_episode_memory", _record)
    pending = await approvals.pending_for_session("s-appr")
    ticket = await approvals.decide(pending.work_id, "apr_1", "approved", actor="u1")
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is True
    assert [item["query"] for item in recorded] == ["안녕"]


async def test_a_stale_approval_after_a_newer_turn_is_refused_and_nothing_reruns(monkeypatch) -> None:
    """앞 턴이 승인을 기다리는 동안 새 턴이 끝났다 -- 옛 승인은 새 턴의 상태 위에서 재개되지 않는다."""
    seen: list[tuple] = []
    turn = {"n": 0}

    def selector(state):
        turn["n"] += 1
        if turn["n"] == 1:
            return {"pending_approvals": PENDING, "approval_decision": None}
        return {}

    def answer(state):
        seen.append((state.get("original_query"), state.get("approval_decision")))
        return {"final_response": f"답: {state.get('original_query')}", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={N.SKILL_TOOL_SELECTOR.value: selector, N.RESP_GENERATOR.value: answer},
        routes={**SKIP_PATH_ROUTES, **AFTER},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    monkeypatch.setattr(
        workflow,
        "_route_after_skill_tool_selector",
        lambda s: "needs_approval" if s.get("pending_approvals") else "skip_orchestrators",
    )
    first = await workflow.execute_workflow(user_input(session_id="s-stale", query="첫 질문"), event_handler=RecordingHandler())
    assert first["interrupted"] is True
    second = await workflow.execute_workflow(user_input(session_id="s-stale", query="둘째 질문"), event_handler=RecordingHandler())
    assert second["success"] is True
    _, lifecycle = workflow.native_stores
    approvals = WorkflowApprovals(workflow, lifecycle)
    assert (await lifecycle.store.get(first["work_id"])).status == "expired"
    assert await approvals.pending_for_session("s-stale") is None
    assert await approvals.decide(first["work_id"], "apr_1", "approved", actor="u1") == Refusal("expired")
    assert seen == [("둘째 질문", None)]


async def test_a_resume_onto_a_newer_session_version_is_refused(monkeypatch) -> None:
    """결정이 행을 잡은 뒤 세션이 바뀌었다 -- 재개는 그 새 상태 위에서 돌지 않고 작업을 실패로 닫는다."""
    workflow, approvals, reached = await _waiting(monkeypatch, session_id="s-moved")
    pending = await approvals.pending_for_session("s-moved")
    ticket = await approvals.decide(pending.work_id, "apr_1", "approved", actor="u1")
    assert isinstance(ticket, ResumeTicket)
    sessions, lifecycle = workflow.native_stores
    saved = await sessions.load("s-moved")
    await sessions.save("s-moved", user_id="u1", state=saved.state, expected_version=saved.version)
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is False
    assert reached == []
    assert (await lifecycle.store.get(pending.work_id)).status == "failed"


async def test_a_wait_without_a_recorded_session_version_is_not_resumed(monkeypatch) -> None:
    """버전을 기록하지 않은 옛 대기 행은 재개를 거절한다 -- 어느 상태 위인지 알 수 없다."""
    workflow, approvals, reached = await _waiting(monkeypatch, session_id="s-oldrow")
    _, lifecycle = workflow.native_stores
    record = await lifecycle.store.waiting_for_session("s-oldrow")
    legacy = {key: value for key, value in record.pending.items() if key != "session_version"}
    lifecycle.store._rows[record.work_id] = replace(record, pending=legacy)
    ticket = await approvals.decide(record.work_id, "apr_1", "approved", actor="u1")
    assert isinstance(ticket, ResumeTicket)
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is False
    assert reached == []
    assert (await lifecycle.store.get(record.work_id)).status == "failed"
