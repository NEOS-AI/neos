"""웹 승인 응답의 네이티브 가지 (spec 2026-10-13 §4.5).

`_respond_native` 를 직접 부른다 -- 소유권 DB 조회(`_require_pending_approval_owner`)는
LangGraph 가지와 같은 앞단이라 여기서 보지 않는다. 재개 결과가 승인 스트림에 어떤 이벤트로
가는지가 이 가지의 계약이다: 성공은 `completed`(답), 실패는 `error`([H4]).
"""

import asyncio
from types import SimpleNamespace

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.runtime import select
from neos.workflow.runtime.approvals import WorkflowApprovals
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

_SESSION = "s-web-native"
_PENDING = [{"request_id": "apr_1", "skill_name": "x"}]
_AFTER = {"_should_continue_after_approval": "approved", "_should_replan": "skip_replan", "_should_regenerate": "proceed"}


async def _waiting(monkeypatch):
    def answer(state):
        return {"final_response": "승인 후 답", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": _PENDING, "approval_decision": None},
            N.RESP_GENERATOR.value: answer,
        },
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval", **_AFTER},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    await workflow.execute_workflow(user_input(session_id=_SESSION), event_handler=RecordingHandler())
    _, lifecycle = workflow.native_stores
    monkeypatch.setattr(select, "_approvals", WorkflowApprovals(workflow, lifecycle))
    return workflow


def _patch_handler(monkeypatch) -> list[tuple[str, dict]]:
    from neos.api.handlers import approval_handlers

    events: list[tuple[str, dict]] = []

    async def _add_event(session_id, event, data):
        events.append((event, data))

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(approval_handlers.stream_manager, "add_event", _add_event)
    monkeypatch.setattr(approval_handlers.stream_manager, "get_session", lambda session_id: None)
    monkeypatch.setattr(approval_handlers.stream_manager, "create_session", lambda session_id, user_id: object())
    monkeypatch.setattr(approval_handlers, "require_stream_session_owner", lambda session, user: None)
    monkeypatch.setattr(approval_handlers, "_mark_approval_resolved", _noop)
    monkeypatch.setattr(approval_handlers, "_add_to_allowlist", _noop)
    return events


async def _drain() -> None:
    for _ in range(20):
        tasks = [t for t in asyncio.all_tasks() if t.get_name().startswith("approval_resume_")]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)


async def _respond(decision: str = "approved"):
    from neos.api.handlers.approval_handlers import ApprovalResponse, _respond_native

    body = ApprovalResponse(session_id=_SESSION, request_id="apr_1", decision=decision)
    user = SimpleNamespace(user_id="u1")
    return await _respond_native(body, user, {"skill_name": "x"})


async def test_a_resumed_answer_is_streamed_as_completed(monkeypatch) -> None:
    await _waiting(monkeypatch)
    events = _patch_handler(monkeypatch)
    result = await _respond()
    assert (result.status, result.session_id, result.decision) == ("resumed", _SESSION, "approved")
    await _drain()
    assert events[-1] == ("completed", {"response": "승인 후 답"})
    assert ("node_complete", {"node": N.RESP_GENERATOR.value}) in events


async def test_a_failed_resume_is_streamed_as_an_error(monkeypatch) -> None:
    """`execute_workflow` 는 예외를 삼키고 `success=False` 를 돌려준다 -- 그것도 `error` 다."""
    workflow = await _waiting(monkeypatch)
    events = _patch_handler(monkeypatch)
    sessions, _ = workflow.native_stores
    await sessions.reset(_SESSION)
    await _respond()
    await _drain()
    kinds = [kind for kind, _ in events]
    assert "completed" not in kinds
    assert events[-1][0] == "error"
    assert events[-1][1]["message"]
