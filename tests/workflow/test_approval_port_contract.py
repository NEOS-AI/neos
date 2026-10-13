"""채널 승인 포트의 계약 (spec 2026-10-13 §5 경계 2).

게이트웨이는 `interrupt_owner`·`decide` 의 이름·시그니처·반환 문자열에 기댄다.
Plan 2 가 안쪽을 승인 서비스로 바꿀 때 이 단언이 그대로 통과해야 한다.
"""

import asyncio

import pytest

from neos.workflow.enums import WorkflowNode as N
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    memory_checkpointer,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

_SESSION = "s-approval"
_PENDING = [{"request_id": "apr_1"}]
_AFTER_APPROVAL_ROUTES = {
    "_should_continue_after_approval": "approved",
    "_should_replan": "skip_replan",
    "_should_regenerate": "proceed",
}


async def _drain_resumes() -> None:
    for _ in range(20):
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task.get_name().startswith("channel_approval_resume_")
        ]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)


async def _interrupted_workflow(monkeypatch, reached: list[str]):
    import neos.api.channels.workflow_approvals as approvals_module

    async def _no_db(request_id, owner_id):
        return None

    monkeypatch.setattr(approvals_module, "_mark_resolved_best_effort", _no_db)

    def answer(state):
        reached.append(N.RESP_GENERATOR.value)
        return {"final_response": "승인 후 답", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": _PENDING, "approval_decision": None},
            N.RESP_GENERATOR.value: answer,
        },
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval", **_AFTER_APPROVAL_ROUTES},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, checkpointer=memory_checkpointer())
    await workflow.execute_workflow(
        user_input(session_id=_SESSION), event_handler=RecordingHandler(), use_checkpointer=True
    )
    return workflow


async def test_the_interrupt_owner_is_the_turns_user(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    assert await port.interrupt_owner(_SESSION) == "u1"


async def test_approving_returns_the_approved_line_and_resumes(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    reached: list[str] = []
    workflow = await _interrupted_workflow(monkeypatch, reached)
    port = RuntimeWorkflowApprovals(workflow)
    reply = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=True)
    assert reply == "apr_1 approved"
    await _drain_resumes()
    assert reached == [N.RESP_GENERATOR.value]


async def test_denying_returns_the_denied_line(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    reply = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=False)
    assert reply == "apr_1 denied"
    await _drain_resumes()


async def test_an_unknown_request_is_not_claimed(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import _INVALID_REQUEST, RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    assert await port.decide(session_id=_SESSION, request_id="apr_x", owner_id="u1", approve=True) == _INVALID_REQUEST


async def test_the_same_decision_twice_is_claimed_once(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import _INVALID_REQUEST, RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    first = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=True)
    await _drain_resumes()
    second = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=True)
    assert first == "apr_1 approved"
    assert second == _INVALID_REQUEST
