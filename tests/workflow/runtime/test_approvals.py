"""승인 서비스 (spec 2026-10-13 §4.5). 그래프가 아니라 작업 행을 읽는다."""

import asyncio

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
    assert await approvals.expire(pending.work_id, "apr_1") is True
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
