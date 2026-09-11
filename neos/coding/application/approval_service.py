from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from neos.coding.domain.approvals import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalResolutionCommit,
)
from neos.coding.sandbox.observability import (
    CodingApprovalAuditEvent,
    NullCodingAuditSink,
)


class ApprovalRepository(Protocol):
    async def resolve_tool_approval(
        self,
        *,
        task_id: str,
        approval_id: str,
        owner_id: str,
        decision: ApprovalDecision,
        now: datetime,
        answers: tuple[str, ...] = (),
    ) -> ApprovalResolutionCommit: ...

    async def expire_pending_approvals(
        self, *, limit: int, now: datetime
    ) -> tuple[ApprovalResolutionCommit, ...]: ...


WakeApproval = Callable[[str, str], Awaitable[None]]


class CodingApprovalService:
    def __init__(
        self,
        repository: ApprovalRepository,
        *,
        wake: WakeApproval,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        metrics=None,
        audit=None,
    ) -> None:
        self._repository = repository
        self._wake = wake
        self._clock = clock
        self._metrics = metrics
        self._audit = audit or NullCodingAuditSink()

    async def _record(self, commit: ApprovalResolutionCommit) -> None:
        approval = commit.approval
        outcome = approval.status.value
        if self._metrics is not None:
            self._metrics.coding_approval_total.labels(
                risk=approval.risk.value, outcome=outcome
            ).inc()
            decided_at = approval.decided_at or self._clock()
            latency = max((decided_at - approval.requested_at).total_seconds(), 0)
            self._metrics.coding_approval_latency_seconds.labels(
                outcome=outcome
            ).observe(latency)
        await self._audit.emit(
            CodingApprovalAuditEvent(
                tool=approval.tool_name,
                risk=approval.risk.value,
                outcome=outcome,
            )
        )

    async def resolve(
        self,
        *,
        task_id: str,
        approval_id: str,
        owner_id: str,
        decision: ApprovalDecision,
        answers: tuple[str, ...] = (),
    ) -> ApprovalResolutionCommit:
        commit = await self._repository.resolve_tool_approval(
            task_id=task_id,
            approval_id=approval_id,
            owner_id=owner_id,
            decision=decision,
            now=self._clock(),
            answers=answers,
        )
        await self._record(commit)
        await self._wake(commit.approval.task_id, commit.approval.checkpoint_id)
        if commit.conflict_code is not None:
            raise ApprovalConflict(commit.conflict_code)
        return commit

    async def expire_pending(
        self, *, limit: int
    ) -> tuple[ApprovalResolutionCommit, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        commits = await self._repository.expire_pending_approvals(
            limit=limit, now=self._clock()
        )
        for commit in commits:
            await self._record(commit)
            await self._wake(commit.approval.task_id, commit.approval.checkpoint_id)
        return commits
