from datetime import timedelta

import pytest

from neos.coding.application.approval_service import CodingApprovalService
from neos.coding.domain.approvals import ApprovalDecision, evaluate_approval
from tests.coding.fakes import RecordingCodingAuditSink, text_turn, tool_turn

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_reconnect_approve_executes_exact_mutation_once(real_loop_harness) -> None:
    secret_content = "changed-after-approval\n"
    harness = await real_loop_harness(
        script=[
            tool_turn(
                "read_file.v1",
                {"path": "calc.py"},
                tool_call_id="tool_read",
            ),
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": secret_content},
                tool_call_id="tool_approval",
            ),
            text_turn("done"),
        ],
        approval_evaluator=evaluate_approval,
    )

    await harness.advance(worker_id="worker-before-reconnect")
    requested_event = await harness.advance(worker_id="worker-before-reconnect")
    requested = next(iter(harness.repository.approvals.values()))
    assert harness.write_count == 0
    assert harness.repository.task_statuses["ct_real"] == "waiting_approval"
    assert requested_event.type == "approval.requested"
    assert secret_content not in repr(requested_event.payload)
    assert requested_event.payload["display_summary"] == {"path": "calc.py"}

    wakeups = []
    audit = RecordingCodingAuditSink()

    async def wake(task_id: str, checkpoint_id: str) -> None:
        wakeups.append((task_id, checkpoint_id))

    await CodingApprovalService(
        harness.repository,
        wake=wake,
        clock=lambda: harness.now.value,
        audit=audit,
    ).resolve(
        task_id="ct_real",
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.APPROVE,
    )
    assert wakeups == [("ct_real", requested.checkpoint_id)]
    assert audit.events == [{
        "tool": "write_file.v1",
        "risk": "workspace_write",
        "outcome": "approved",
    }]

    harness.elapse(timedelta(seconds=1))
    await harness.advance_until_complete(worker_id="worker-after-reconnect")
    assert harness.write_count == 1
    assert await harness.session.read_file("calc.py") == secret_content.encode()


@pytest.mark.asyncio
async def test_denial_resumes_without_executing_mutation(real_loop_harness) -> None:
    harness = await real_loop_harness(
        script=[
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "must-not-run"},
                tool_call_id="tool_denied",
            ),
            text_turn("denied safely"),
        ],
        approval_evaluator=evaluate_approval,
    )
    await harness.advance()
    requested = next(iter(harness.repository.approvals.values()))

    async def wake(_task_id: str, _checkpoint_id: str) -> None:
        return None

    await CodingApprovalService(
        harness.repository, wake=wake, clock=lambda: harness.now.value
    ).resolve(
        task_id="ct_real",
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.DENY,
    )
    await harness.advance_until_complete(worker_id="replacement")

    assert harness.write_count == 0
    assert await harness.session.read_file("calc.py") != b"must-not-run"
