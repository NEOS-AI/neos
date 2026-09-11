"""Coding-agent port used by ChannelGateway. Injectable in tests."""

from __future__ import annotations

from typing import Protocol


class ChannelCodingPort(Protocol):
    async def start_task(self, *, owner_id: str, prompt: str) -> str: ...

    async def stop_task(self, *, task_id: str, owner_id: str) -> None: ...

    async def status(self, *, task_id: str, owner_id: str) -> str: ...

    async def decide(
        self, *, task_id: str, owner_id: str, approve: bool, approval_id: str
    ) -> str: ...


class RuntimeChannelCoding:
    async def start_task(self, *, owner_id: str, prompt: str) -> str:
        from neos.coding.runtime import coding_service

        task = await coding_service.create_task(owner_id=owner_id, prompt=prompt)
        return task.task_id

    async def stop_task(self, *, task_id: str, owner_id: str) -> None:
        from neos.coding.runtime import coding_run_service

        await coding_run_service.stop(task_id=task_id)

    async def status(self, *, task_id: str, owner_id: str) -> str:
        from neos.coding.runtime import coding_service

        snapshot = await coding_service.snapshot(task_id, owner_id)
        if snapshot is None:
            return "Coding task not found."
        return f"{snapshot.task.task_id} {snapshot.task.status.value}"

    async def decide(
        self, *, task_id: str, owner_id: str, approve: bool, approval_id: str
    ) -> str:
        from neos.coding.domain.approvals import ApprovalDecision, ApprovalStatus
        from neos.coding.runtime import coding_approval_service, coding_snapshot_service

        target = approval_id
        if not target:
            snapshot = await coding_snapshot_service.get_owned(task_id, owner_id)
            if snapshot is None:
                return "Coding task not found."
            pending = [
                item
                for item in snapshot.approvals
                if item.status is ApprovalStatus.PENDING
            ]
            if not pending:
                return "No pending coding approval."
            target = pending[-1].approval_id
        commit = await coding_approval_service.resolve(
            task_id=task_id,
            approval_id=target,
            owner_id=owner_id,
            decision=(
                ApprovalDecision.APPROVE if approve else ApprovalDecision.DENY
            ),
        )
        return f"{commit.approval.approval_id} {commit.approval.status.value}"
