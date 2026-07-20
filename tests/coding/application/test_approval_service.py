from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.application.approval_service import CodingApprovalService
from neos.coding.domain.approvals import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalResolutionCommit,
    ApprovalStatus,
    CodingApproval,
)
from neos.coding.domain.events import make_event
from neos.coding.tools.registry import ToolRisk


NOW = datetime(2026, 7, 21, 1, 0, tzinfo=UTC)


def approval(*, expires_at=None) -> CodingApproval:
    return CodingApproval(
        approval_id="ca_1",
        task_id="ct_1",
        run_id="cr_1",
        tool_call_id="tool_1",
        checkpoint_id="cc_1",
        tool_name="write_file.v1",
        risk=ToolRisk.WORKSPACE_WRITE,
        workspace_revision="rev-1",
        request_hash="a" * 64,
        display_summary={"path": "src/main.py"},
        status=ApprovalStatus.PENDING,
        requested_by="user-1",
        requested_at=NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(minutes=14),
    )


class Repository:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    async def resolve_tool_approval(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    async def expire_pending_approvals(self, **kwargs):
        self.calls.append(kwargs)
        return tuple(self.result or ())


class Wake:
    def __init__(self) -> None:
        self.calls = []

    async def __call__(self, task_id, checkpoint_id) -> None:
        self.calls.append((task_id, checkpoint_id))


def resolution(status, *, conflict_code=None):
    pending = approval(expires_at=NOW if status is ApprovalStatus.EXPIRED else None)
    decision = (
        ApprovalDecision.APPROVE
        if status is ApprovalStatus.APPROVED
        else ApprovalDecision.DENY if status is ApprovalStatus.DENIED else None
    )
    resolved = replace(
        pending,
        status=status,
        decision=decision,
        decided_by="user-1" if decision else None,
        decided_at=NOW,
    )
    event = make_event(
        task_id="ct_1", seq=3, event_type=f"approval.{status.value}",
        payload={"approval_id": "ca_1", "status": status.value}, now=NOW,
    )
    return ApprovalResolutionCommit(resolved, (event,), conflict_code)


async def test_resolve_wakes_checkpoint_only_after_repository_commit() -> None:
    repository = Repository(resolution(ApprovalStatus.APPROVED))
    wake = Wake()
    service = CodingApprovalService(repository, wake=wake, clock=lambda: NOW)

    committed = await service.resolve(
        task_id="ct_1", approval_id="ca_1", owner_id="user-1",
        decision=ApprovalDecision.APPROVE,
    )

    assert committed.approval.status is ApprovalStatus.APPROVED
    assert wake.calls == [("ct_1", "cc_1")]


async def test_expired_decision_commits_wakes_then_surfaces_conflict() -> None:
    repository = Repository(
        resolution(ApprovalStatus.EXPIRED, conflict_code="approval_expired")
    )
    wake = Wake()
    service = CodingApprovalService(repository, wake=wake, clock=lambda: NOW)

    with pytest.raises(ApprovalConflict, match="approval_expired"):
        await service.resolve(
            task_id="ct_1", approval_id="ca_1", owner_id="user-1",
            decision=ApprovalDecision.APPROVE,
        )

    assert wake.calls == [("ct_1", "cc_1")]


async def test_repository_failure_never_wakes_worker() -> None:
    repository = Repository(error=RuntimeError("db unavailable"))
    wake = Wake()
    service = CodingApprovalService(repository, wake=wake, clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="db unavailable"):
        await service.resolve(
            task_id="ct_1", approval_id="ca_1", owner_id="user-1",
            decision=ApprovalDecision.DENY,
        )

    assert wake.calls == []


async def test_expiry_batch_wakes_every_committed_checkpoint() -> None:
    commits = (
        resolution(ApprovalStatus.EXPIRED),
        replace(
            resolution(ApprovalStatus.EXPIRED),
            approval=replace(
                resolution(ApprovalStatus.EXPIRED).approval,
                approval_id="ca_2", task_id="ct_2", checkpoint_id="cc_2",
            ),
        ),
    )
    repository = Repository(commits)
    wake = Wake()
    service = CodingApprovalService(repository, wake=wake, clock=lambda: NOW)

    result = await service.expire_pending(limit=10)

    assert result == commits
    assert wake.calls == [("ct_1", "cc_1"), ("ct_2", "cc_2")]
