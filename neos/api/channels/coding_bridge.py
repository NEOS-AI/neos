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

    async def steer(self, *, task_id: str, owner_id: str, instruction: str) -> str: ...


class RuntimeChannelCoding:
    async def start_task(self, *, owner_id: str, prompt: str) -> str:
        from neos.coding.runtime import coding_service

        task = await coding_service.create_task(owner_id=owner_id, prompt=prompt)
        return task.task_id

    async def stop_task(self, *, task_id: str, owner_id: str) -> None:
        from neos.coding.runtime import coding_run_service

        await coding_run_service.stop(task_id=task_id, owner_id=owner_id)

    async def status(self, *, task_id: str, owner_id: str) -> str:
        from neos.coding.runtime import coding_service

        snapshot = await coding_service.snapshot(task_id, owner_id)
        if snapshot is None:
            return "Coding task not found."
        status = snapshot.task.status.value
        if status == "waiting_approval":
            from neos.coding.domain.approvals import ApprovalStatus
            from neos.coding.runtime import coding_snapshot_service

            projection = await coding_snapshot_service.get_owned(task_id, owner_id)
            pending = [
                item
                for item in (projection.approvals if projection is not None else ())
                if item.status is ApprovalStatus.PENDING
            ]
            if pending:
                latest = pending[-1]
                return (
                    f"{snapshot.task.task_id} waiting_approval "
                    f"{latest.approval_id} {latest.tool_name}"
                )
        return f"{snapshot.task.task_id} {status}"

    async def decide(
        self, *, task_id: str, owner_id: str, approve: bool, approval_id: str
    ) -> str:
        from neos.coding.domain.approvals import (
            ApprovalConflict,
            ApprovalDecision,
            ApprovalStatus,
            requires_approval_answers,
        )
        from neos.coding.runtime import coding_approval_service, coding_snapshot_service

        target = approval_id
        snapshot = await coding_snapshot_service.get_owned(task_id, owner_id)
        if snapshot is None:
            return "Coding task not found."
        pending = [
            item
            for item in snapshot.approvals
            if item.status is ApprovalStatus.PENDING
        ]
        if not target:
            if not pending:
                return "No pending coding approval."
            target = pending[-1].approval_id
        chosen = next((item for item in pending if item.approval_id == target), None)
        if (
            approve
            and chosen is not None
            and requires_approval_answers(chosen.tool_name)
        ):
            return "Answer this question in the Code UI."
        try:
            commit = await coding_approval_service.resolve(
                task_id=task_id,
                approval_id=target,
                owner_id=owner_id,
                decision=(
                    ApprovalDecision.APPROVE if approve else ApprovalDecision.DENY
                ),
            )
        except ApprovalConflict as error:
            if str(error) == "answers_required":
                return "Answer this question in the Code UI."
            raise
        return f"{commit.approval.approval_id} {commit.approval.status.value}"

    async def steer(self, *, task_id: str, owner_id: str, instruction: str) -> str:
        from neos.coding.domain.errors import CodingTaskNotFound
        from neos.coding.domain.phases import SteeringMode
        from neos.coding.runtime import coding_run_service

        try:
            await coding_run_service.steer(
                task_id=task_id,
                owner_id=owner_id,
                instruction=instruction,
                mode=SteeringMode.SAFE_POINT,
            )
        except CodingTaskNotFound:
            return "No coding task in this thread."
        return f"Steered {task_id}"
