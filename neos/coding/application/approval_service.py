from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from neos.coding.domain.approvals import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalResolutionCommit,
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
    ) -> None:
        self._repository = repository
        self._wake = wake
        self._clock = clock

    async def resolve(
        self,
        *,
        task_id: str,
        approval_id: str,
        owner_id: str,
        decision: ApprovalDecision,
    ) -> ApprovalResolutionCommit:
        commit = await self._repository.resolve_tool_approval(
            task_id=task_id,
            approval_id=approval_id,
            owner_id=owner_id,
            decision=decision,
            now=self._clock(),
        )
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
            await self._wake(commit.approval.task_id, commit.approval.checkpoint_id)
        return commits
