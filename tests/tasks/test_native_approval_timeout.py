"""타임아웃 자동 거부의 네이티브 가지 (spec 2026-10-13 §4.5, R6).

그래프 객체가 아니라 작업 행을 읽는다 -- 워커에서도 같은 경로다.
"""

import pytest

from neos.tasks.scheduled_task_runner import _inject_timeout_rejection
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

_SESSION = "s-timeout-native"


async def _native_workflow(monkeypatch, *, wait: bool):
    reached: list[str] = []

    def answer(state):
        reached.append(N.RESP_GENERATOR.value)
        return {"final_response": "답", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {
                "pending_approvals": [{"request_id": "apr_1"}],
                "approval_decision": None,
            },
            N.RESP_GENERATOR.value: answer,
        },
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval"},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    if wait:
        await workflow.execute_workflow(user_input(session_id=_SESSION), event_handler=RecordingHandler())
    _, lifecycle = workflow.native_stores
    monkeypatch.setattr(select, "_approvals", WorkflowApprovals(workflow, lifecycle))
    return lifecycle, reached


async def test_a_timeout_expires_the_waiting_work_without_resuming(monkeypatch) -> None:
    lifecycle, reached = await _native_workflow(monkeypatch, wait=True)
    waiting = await lifecycle.store.waiting_for_session(_SESSION)
    assert waiting is not None
    assert await _inject_timeout_rejection(_SESSION, "apr_1") is True
    assert (await lifecycle.store.get(waiting.work_id)).status == "expired"
    assert await lifecycle.store.waiting_for_session(_SESSION) is None
    assert reached == []


async def test_a_timeout_without_waiting_work_does_nothing(monkeypatch) -> None:
    await _native_workflow(monkeypatch, wait=False)
    assert await _inject_timeout_rejection(_SESSION, "apr_1") is False
