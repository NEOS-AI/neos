import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any

from neos.coding.domain.durability import (
    ExecutionLease,
    PhaseCheckpointCommit,
    PhaseStart,
    StaleExecutionLease,
    SteeringApplication,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.domain.events import make_event
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhaseStatus,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    next_phase_attempt,
)


class InMemoryCodingRunRepository:
    def __init__(self, *, completed_tools=None, active_run=None) -> None:
        self.completed_tools = dict(completed_tools or {})
        self.active_run = active_run
        self.checkpoints = []
        self.tool_execution_calls = []
        self.created_runs = []
        self.interrupt_calls = []
        self.applied_steering = []
        self.steering_requests = []
        self.steering_claims = {}
        self.phases = []
        self.execution_leases = {}
        self.tool_claims = {}
        self._durability_lock = asyncio.Lock()
        self._durability_seq = 0
        self.begin_phase_calls = 0
        self.phase_commit_calls = 0

    async def acquire_execution_lease(
        self,
        *,
        task_id,
        run_id,
        worker_id,
        now,
        expires_at,
    ):
        async with self._durability_lock:
            current = self.execution_leases.get(task_id)
            if current is not None and current.expires_at > now:
                return None
            token = current.fencing_token + 1 if current else 1
            lease = ExecutionLease(
                task_id=task_id,
                run_id=run_id,
                worker_id=worker_id,
                fencing_token=token,
                acquired_at=now,
                expires_at=expires_at,
                recovered=(
                    current is not None and current.worker_id != worker_id
                ),
            )
            self.execution_leases[task_id] = lease
            return lease

    async def renew_execution_lease(
        self, lease, *, now, expires_at
    ):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            renewed = ExecutionLease(
                task_id=lease.task_id,
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                fencing_token=lease.fencing_token,
                acquired_at=lease.acquired_at,
                expires_at=expires_at,
            )
            self.execution_leases[lease.task_id] = renewed
            return renewed

    async def release_execution_lease(self, lease, *, now) -> None:
        async with self._durability_lock:
            self._require_current_lease(lease)
            self.execution_leases[lease.task_id] = ExecutionLease(
                task_id=lease.task_id,
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                fencing_token=lease.fencing_token,
                acquired_at=min(
                    lease.acquired_at, now - timedelta(microseconds=1)
                ),
                expires_at=now,
            )

    async def claim_tool_execution(
        self,
        *,
        lease,
        tool_call_id,
        now,
        claim_expires_at,
    ):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            completed = self.completed_tools.get((lease.task_id, tool_call_id))
            if completed is not None:
                return ToolExecutionClaim(
                    ToolExecutionDisposition.COMPLETED,
                    tool_call_id,
                    lease,
                    completed,
                )
            current = self.tool_claims.get((lease.task_id, tool_call_id))
            if current is not None and current[1] > now:
                return ToolExecutionClaim(
                    ToolExecutionDisposition.BUSY, tool_call_id, lease
                )
            claim = ToolExecutionClaim(
                ToolExecutionDisposition.CLAIMED, tool_call_id, lease
            )
            self.tool_claims[(lease.task_id, tool_call_id)] = (
                claim,
                claim_expires_at,
            )
            return claim

    async def complete_tool_execution(self, claim, *, result, now):
        async with self._durability_lock:
            self._require_current_lease(claim.lease, now=now)
            key = (claim.lease.task_id, claim.tool_call_id)
            current = self.tool_claims.get(key)
            if current is None or current[0] != claim:
                raise StaleExecutionLease(claim.lease.task_id)
            self.completed_tools[key] = dict(result)
            self.tool_execution_calls.append(
                {
                    "task_id": claim.lease.task_id,
                    "run_id": claim.lease.run_id,
                    "tool_call_id": claim.tool_call_id,
                    "result": dict(result),
                    "completed_at": now,
                }
            )
            self._durability_seq += 1
            return make_event(
                task_id=claim.lease.task_id,
                seq=self._durability_seq,
                event_type="tool.completed",
                payload={"result": dict(result), "reused": False},
                now=now,
                run_id=claim.lease.run_id,
                tool_call_id=claim.tool_call_id,
            )

    def _require_current_lease(self, lease, *, now=None) -> None:
        current = self.execution_leases.get(lease.task_id)
        if (
            current is None
            or current.run_id != lease.run_id
            or current.worker_id != lease.worker_id
            or current.fencing_token != lease.fencing_token
            or (now is not None and current.expires_at <= now)
        ):
            raise StaleExecutionLease(
                f"{lease.task_id}: expected={lease!r}, current={current!r}, now={now!r}"
            )

    async def begin_phase(self, *, lease, kind, now):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            self.begin_phase_calls += 1
            active = next(
                (
                    phase
                    for phase in self.phases
                    if phase.task_id == lease.task_id
                    and phase.run_id == lease.run_id
                    and phase.kind is kind
                    and phase.status is CodingPhaseStatus.ACTIVE
                ),
                None,
            )
            if active is not None:
                return PhaseStart(active, None, True)
            phase = next_phase_attempt(
                task_id=lease.task_id,
                run_id=lease.run_id,
                kind=kind,
                existing=[(item.kind, item.attempt) for item in self.phases],
                now=now,
            )
            self.phases.append(phase)
            self._durability_seq += 1
            event = make_event(
                task_id=lease.task_id,
                seq=self._durability_seq,
                event_type="phase.started",
                payload={"phase": kind.value, "attempt": phase.attempt},
                now=now,
                run_id=lease.run_id,
            )
            return PhaseStart(phase, event, False)

    async def commit_phase_checkpoint(
        self,
        *,
        lease,
        phase,
        tool_call_id,
        result,
        loop_state,
        workspace_revision,
        now,
    ):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            self.phase_commit_calls += 1
            self._durability_seq += 1
            checkpoint = CodingCheckpoint(
                checkpoint_id=f"cc_{phase.phase_id}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                seq=self._durability_seq,
                loop_state=dict(loop_state),
                workspace_revision=workspace_revision,
                created_at=now,
            )
            completed = replace(
                phase,
                status=CodingPhaseStatus.COMPLETED,
                completed_at=now,
            )
            self.checkpoints.append(checkpoint)
            self.phases = [
                completed if item.phase_id == phase.phase_id else item
                for item in self.phases
            ]
            event = make_event(
                task_id=lease.task_id,
                seq=checkpoint.seq,
                event_type="phase.completed",
                payload={
                    "phase": phase.kind.value,
                    "attempt": phase.attempt,
                    **dict(result),
                },
                now=now,
                run_id=lease.run_id,
                tool_call_id=tool_call_id,
                checkpoint_id=checkpoint.checkpoint_id,
            )
            return PhaseCheckpointCommit(checkpoint, event, completed)

    async def create_run(self, run) -> None:
        self.created_runs.append(run)
        self.active_run = run

    async def update_run(self, run) -> None:
        self.active_run = run

    async def latest_run(self, task_id: str):
        if self.active_run is None or self.active_run.task_id != task_id:
            return None
        return self.active_run

    async def save_checkpoint(self, checkpoint) -> None:
        if not any(
            existing.checkpoint_id == checkpoint.checkpoint_id
            for existing in self.checkpoints
        ):
            self.checkpoints.append(checkpoint)

    async def latest_checkpoint(self, task_id: str):
        matches = [item for item in self.checkpoints if item.task_id == task_id]
        return max(matches, key=lambda item: item.seq, default=None)

    async def completed_tool_result(self, task_id: str, tool_call_id: str):
        return self.completed_tools.get((task_id, tool_call_id)) or (
            self.completed_tools.get(tool_call_id)
        )

    async def record_tool_result(self, **record: Any) -> None:
        self.tool_execution_calls.append(record)
        key = (record["task_id"], record["tool_call_id"])
        self.completed_tools.setdefault(key, record["result"])

    async def queue_steering(self, request) -> None:
        self.steering_requests.append(request)

    async def claim_pending_steering(self, task_id: str):
        for request in self.steering_requests:
            if request.task_id == task_id and request not in self.applied_steering:
                return request
        return None

    async def apply_steering(self, request) -> None:
        self.applied_steering.append(request)

    async def apply_steering_at_safe_point(
        self,
        *,
        lease,
        checkpoint,
        worker_id,
        claim_expires_at,
        now,
    ):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            request = next(
                (
                    item
                    for item in self.steering_requests
                    if item.task_id == lease.task_id
                    and item.mode is SteeringMode.SAFE_POINT
                    and item not in self.applied_steering
                    and (
                        item.steering_id not in self.steering_claims
                        or self.steering_claims[item.steering_id][1] <= now
                    )
                ),
                None,
            )
            if request is None:
                return None
            self.steering_claims[request.steering_id] = (
                worker_id,
                claim_expires_at,
            )
            self._durability_seq += 1
            loop_state = dict(checkpoint.loop_state)
            loop_state["phase_index"] = -1
            loop_state["current_instruction"] = request.instruction
            loop_state["pending_instruction"] = None
            steering_checkpoint = CodingCheckpoint(
                checkpoint_id=f"cc_steer_{request.steering_id}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                seq=self._durability_seq,
                loop_state=loop_state,
                workspace_revision=checkpoint.workspace_revision,
                created_at=now,
            )
            previous = self.active_run
            if previous is None or previous.run_id != lease.run_id:
                raise StaleExecutionLease(lease.task_id)
            cancelled = replace(
                previous,
                status=CodingRunStatus.CANCELLED,
                completed_at=now,
            )
            run = CodingRun(
                run_id=f"cr_steer_{request.steering_id}",
                task_id=lease.task_id,
                attempt=previous.attempt + 1,
                status=CodingRunStatus.RUNNING,
                resume_from_checkpoint_id=steering_checkpoint.checkpoint_id,
                started_at=now,
            )
            next_lease = ExecutionLease(
                task_id=lease.task_id,
                run_id=run.run_id,
                worker_id=worker_id,
                fencing_token=lease.fencing_token + 1,
                acquired_at=now,
                expires_at=claim_expires_at,
            )
            applied = replace(
                request,
                applied_checkpoint_id=steering_checkpoint.checkpoint_id,
            )
            event = make_event(
                task_id=lease.task_id,
                seq=self._durability_seq,
                event_type="steer.applied",
                payload={
                    "steering_id": request.steering_id,
                    "mode": request.mode.value,
                    "instruction": request.instruction,
                },
                now=now,
                run_id=lease.run_id,
                checkpoint_id=steering_checkpoint.checkpoint_id,
            )
            self.checkpoints.append(steering_checkpoint)
            self.applied_steering.append(applied)
            self.created_runs.append(run)
            self.active_run = run
            self.execution_leases[lease.task_id] = next_lease
            return SteeringApplication(
                applied,
                steering_checkpoint,
                cancelled,
                run,
                next_lease,
                event,
            )

    async def commit_interruption(
        self,
        *,
        lease,
        request,
        workspace_revision,
        process_stopped,
        now,
    ):
        if not process_stopped:
            raise ValueError("process must be stopped before interruption commit")
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            previous = self.active_run
            if previous is None or previous.run_id != lease.run_id:
                raise StaleExecutionLease(lease.task_id)
            self._durability_seq += 1
            checkpoint = CodingCheckpoint(
                checkpoint_id=f"cc_interrupt_{request.steering_id}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                seq=self._durability_seq,
                loop_state={
                    "phase_index": -1,
                    "transcript": [],
                    "current_instruction": request.instruction,
                    "pending_instruction": None,
                },
                workspace_revision=workspace_revision,
                created_at=now,
            )
            cancelled = replace(
                previous,
                status=CodingRunStatus.CANCELLED,
                completed_at=now,
            )
            run = CodingRun(
                run_id=f"cr_interrupt_{request.steering_id}",
                task_id=lease.task_id,
                attempt=previous.attempt + 1,
                status=CodingRunStatus.RUNNING,
                resume_from_checkpoint_id=checkpoint.checkpoint_id,
                started_at=now,
            )
            next_lease = ExecutionLease(
                task_id=lease.task_id,
                run_id=run.run_id,
                worker_id=lease.worker_id,
                fencing_token=lease.fencing_token + 1,
                acquired_at=now,
                expires_at=lease.expires_at,
            )
            applied = replace(
                request, applied_checkpoint_id=checkpoint.checkpoint_id
            )
            event = make_event(
                task_id=lease.task_id,
                seq=checkpoint.seq,
                event_type="run.interrupted",
                payload={
                    "steering_id": request.steering_id,
                    "process_stopped": True,
                },
                now=now,
                run_id=lease.run_id,
                checkpoint_id=checkpoint.checkpoint_id,
            )
            self.checkpoints.append(checkpoint)
            self.applied_steering.append(applied)
            self.created_runs.append(run)
            self.active_run = run
            self.execution_leases[lease.task_id] = next_lease
            return SteeringApplication(
                applied,
                checkpoint,
                cancelled,
                run,
                next_lease,
                event,
            )

    async def phase_history(self, task_id: str):
        return tuple(
            (phase.kind, phase.attempt)
            for phase in self.phases
            if phase.task_id == task_id
        )

    async def save_phase(self, phase) -> None:
        self.phases = [
            existing
            for existing in self.phases
            if existing.phase_id != phase.phase_id
        ]
        self.phases.append(phase)
