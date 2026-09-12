import asyncio
from collections.abc import Iterable
from dataclasses import asdict, replace
from datetime import timedelta
from typing import Any

from neos.coding.domain.durability import (
    ExecutionLease,
    ModelCheckpointCommit,
    PhaseCheckpointCommit,
    PhaseStart,
    RunLifecycleCommit,
    StaleExecutionLease,
    SteeringApplication,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.domain.approvals import (
    ApprovalConflict,
    ApprovalDecision,
    ApprovalNotFound,
    ApprovalRequestCommit,
    ApprovalResolutionCommit,
    ApprovalStatus,
    CodingApproval,
    approval_display_summary,
    canonical_approval_hash,
    requires_approval_answers,
)
from neos.coding.domain.events import make_event
from neos.coding.domain.text_parts import (
    CodingTextPart,
    ModelTextPartCommit,
    TextPartConflict,
    TextPartStatus,
)
from neos.coding.domain.workspace_edits import (
    WorkspaceEditApplication,
    WorkspaceEditStatus,
)
from neos.coding.loop.base import EXPECTED_CHECKPOINT_OMITTED

from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhaseStatus,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    next_phase_attempt,
)
from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    TextDelta,
    ToolCallCompleted,
)


def tool_turn(
    name: str,
    input: dict[str, Any],
    *,
    tool_call_id: str,
) -> tuple[object, ...]:
    return (
        ToolCallCompleted(tool_call_id, name, input),
        ModelCompleted("tool_use", ModelUsage(1, 1)),
    )


def text_turn(text: str) -> tuple[object, ...]:
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(1, 1)))


class ScriptedCodingModel:
    def __init__(self, script: Iterable[Iterable[object]]) -> None:
        self.script = [tuple(turn) for turn in script]
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        for event in self.script.pop(0):
            yield event


class RecordingMetric:
    def __init__(self, name: str, records: list[tuple[str, dict[str, str]]]) -> None:
        self._name = name
        self._records = records
        self._labels: dict[str, str] = {}

    def labels(self, **labels):
        metric = RecordingMetric(self._name, self._records)
        metric._labels = labels
        return metric

    def inc(self) -> None:
        self._records.append((self._name, self._labels))


class RecordingCodingLoopMetrics:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, str]]] = []
        self.coding_model_turn_total = RecordingMetric(
            "coding_model_turn_total", self.records
        )
        self.coding_tool_execution_total = RecordingMetric(
            "coding_tool_execution_total", self.records
        )


class RecordingCodingAuditSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, event) -> None:
        self.events.append(asdict(event))


class InMemorySandboxBindingRepository:
    def __init__(self, leases) -> None:
        self.current = None
        self._leases = leases

    async def get(self, task_id):
        if self.current is None or self.current.task_id != task_id:
            return None
        return self.current

    def _require_lease(self, lease, now):
        current = self._leases.execution_leases.get(lease.task_id)
        if current != lease or current.expires_at <= now:
            raise StaleExecutionLease(lease.task_id)

    async def validate_fenced(self, *, lease, now):
        self._require_lease(lease, now)

    async def create_fenced(self, binding, *, lease, now):
        self._require_lease(lease, now)
        if self.current is not None:
            return False
        self.current = binding
        return True

    async def replace_fenced(self, binding, *, expected_version, lease, now):
        self._require_lease(lease, now)
        if self.current is None or self.current.version != expected_version:
            return None
        self.current = replace(binding, version=expected_version + 1)
        return self.current

    async def replace_admin(self, binding, *, expected_version, now):
        if self.current is None or self.current.version != expected_version:
            return None
        self.current = replace(binding, version=expected_version + 1)
        return self.current

    async def delete_admin(self, task_id, *, expected_version):
        if self.current is None or self.current.version != expected_version:
            return False
        self.current = None
        return True


class InMemoryCodingRunRepository:
    def __init__(
        self,
        *,
        completed_tools=None,
        active_run=None,
        task_prompts=None,
        workspace_edits=None,
    ) -> None:
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
        self.approvals = {}
        self.text_parts = {}
        self.workspace_edits = {
            edit.edit_id: edit for edit in (workspace_edits or ())
        }
        self._durability_lock = asyncio.Lock()
        self._durability_seq = 0
        self.begin_phase_calls = 0
        self.phase_commit_calls = 0
        self.model_commit_calls = 0
        self.task_prompts = dict(task_prompts or {})
        self.task_statuses = {task_id: "queued" for task_id in self.task_prompts}

    def _canonical_run(self, task_id):
        runs_by_id = {
            run.run_id: run for run in self.created_runs if run.task_id == task_id
        }
        if self.active_run is not None and self.active_run.task_id == task_id:
            runs_by_id[self.active_run.run_id] = self.active_run
        return max(runs_by_id.values(), key=lambda run: run.attempt, default=None)

    async def ensure_run_started(
        self,
        *,
        task_id,
        instruction,
        development_mode,
        now,
    ):
        async with self._durability_lock:
            if task_id not in self.task_statuses:
                raise RuntimeError(f"coding task does not exist: {task_id}")
            if (
                self.active_run is not None
                and self.active_run.task_id == task_id
                and self.active_run.status is CodingRunStatus.RUNNING
            ):
                return self.active_run
            if self.task_statuses[task_id] in {
                "completed",
                "failed",
                "cancelled",
            }:
                if self.active_run is None:
                    raise RuntimeError(f"terminal coding task has no run: {task_id}")
                return self.active_run
            if self.task_statuses[task_id] == "queued" and not development_mode:
                raise ValueError("queued task fast path requires development mode")
            attempts = [
                run.attempt for run in self.created_runs if run.task_id == task_id
            ]
            run = CodingRun(
                run_id=f"cr_{task_id}_{max(attempts, default=0) + 1}",
                task_id=task_id,
                attempt=max(attempts, default=0) + 1,
                status=CodingRunStatus.RUNNING,
                resume_from_checkpoint_id=None,
                started_at=now,
            )
            self.created_runs.append(run)
            self.active_run = run
            self.task_statuses[task_id] = "running"
            self._durability_seq += 1
            return run

    async def complete_run(self, *, lease, now):
        return await self._commit_terminal_run(
            lease=lease,
            status=CodingRunStatus.COMPLETED,
            payload={"status": "completed"},
            now=now,
        )

    async def fail_run(self, *, lease, error_code, now):
        if not error_code or not error_code.replace("_", "").isalnum():
            raise ValueError("error_code must be normalized")
        return await self._commit_terminal_run(
            lease=lease,
            status=CodingRunStatus.FAILED,
            payload={"status": "failed", "error_code": error_code},
            now=now,
        )

    async def cancel_run(self, *, lease, now):
        return await self._commit_terminal_run(
            lease=lease,
            status=CodingRunStatus.CANCELLED,
            payload={"status": "cancelled"},
            now=now,
        )

    async def mark_task_cancelled(self, *, task_id, now):
        del now
        if self.task_statuses.get(task_id) not in {
            "completed",
            "failed",
            "cancelled",
        }:
            self.task_statuses[task_id] = "cancelled"

    async def _commit_terminal_run(self, *, lease, status, payload, now):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            if self.active_run is None or self.active_run.run_id != lease.run_id:
                raise StaleExecutionLease(lease.task_id)
            run = replace(self.active_run, status=status, completed_at=now)
            self.active_run = run
            self.created_runs = [
                run if item.run_id == run.run_id else item for item in self.created_runs
            ]
            self.task_statuses[lease.task_id] = status.value
            self._durability_seq += 1
            event = make_event(
                task_id=lease.task_id,
                seq=self._durability_seq,
                event_type=f"run.{status.value}",
                payload=dict(payload),
                now=now,
                run_id=lease.run_id,
            )
            return RunLifecycleCommit(run=run, event=event)

    async def claimable_task_ids(self, *, limit):
        if limit < 1:
            raise ValueError("limit must be positive")
        return tuple(
            task_id
            for task_id, status in self.task_statuses.items()
            if status in {"queued", "running"}
        )[:limit]

    async def claimable_delivery_tokens(self, *, limit):
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._durability_lock:
            deliveries = []
            for task_id, task_status in self.task_statuses.items():
                if task_status not in {"queued", "running"}:
                    continue
                canonical = self._canonical_run(task_id)
                if canonical is None:
                    continue
                if canonical.status is not CodingRunStatus.RUNNING:
                    continue
                latest = max(
                    (
                        checkpoint
                        for checkpoint in self.checkpoints
                        if checkpoint.task_id == task_id
                        and checkpoint.run_id == canonical.run_id
                    ),
                    key=lambda checkpoint: checkpoint.seq,
                    default=None,
                )
                deliveries.append(
                    (task_id, latest.checkpoint_id if latest is not None else None)
                )
                if len(deliveries) == limit:
                    break
            return tuple(deliveries)

    async def acquire_execution_lease(
        self,
        *,
        task_id,
        run_id,
        worker_id,
        now,
        expires_at,
        expected_checkpoint_id=EXPECTED_CHECKPOINT_OMITTED,
    ):
        async with self._durability_lock:
            canonical = self._canonical_run(task_id)
            if canonical is None:
                return None
            if (
                canonical.run_id != run_id
                or canonical.status is not CodingRunStatus.RUNNING
            ):
                return None
            latest_checkpoint = max(
                (
                    checkpoint
                    for checkpoint in self.checkpoints
                    if checkpoint.task_id == task_id
                    and checkpoint.run_id == canonical.run_id
                ),
                key=lambda checkpoint: checkpoint.seq,
                default=None,
            )
            latest = (
                latest_checkpoint.checkpoint_id
                if latest_checkpoint is not None
                else None
            )
            if (
                expected_checkpoint_id is not EXPECTED_CHECKPOINT_OMITTED
                and latest != expected_checkpoint_id
            ):
                return None
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
                recovered=(current is not None and current.worker_id != worker_id),
            )
            self.execution_leases[task_id] = lease
            return lease

    async def renew_execution_lease(self, lease, *, now, expires_at):
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
                acquired_at=min(lease.acquired_at, now - timedelta(microseconds=1)),
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
                stored_claim = current[0]
                if (
                    getattr(stored_claim, "disposition", None)
                    is ToolExecutionDisposition.DELEGATED
                ):
                    adopted = ToolExecutionClaim(
                        ToolExecutionDisposition.DELEGATED,
                        tool_call_id,
                        lease,
                        getattr(stored_claim, "result", None),
                    )
                    self.tool_claims[(lease.task_id, tool_call_id)] = (
                        adopted,
                        claim_expires_at,
                    )
                    return adopted
                return ToolExecutionClaim(
                    ToolExecutionDisposition.BUSY, tool_call_id, lease
                )
            disposition = (
                ToolExecutionDisposition.RECLAIMED
                if current is not None
                else ToolExecutionDisposition.CLAIMED
            )
            claim = ToolExecutionClaim(disposition, tool_call_id, lease)
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
            if current is None or not self._claim_matches_current_fencing(
                current[0], claim
            ):
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

    async def mark_tool_delegated(
        self,
        claim,
        *,
        child_run_id,
        child_checkpoint_id,
        claim_expires_at,
        now,
    ) -> None:
        async with self._durability_lock:
            self._require_current_lease(claim.lease, now=now)
            if claim.disposition not in {
                ToolExecutionDisposition.CLAIMED,
                ToolExecutionDisposition.RECLAIMED,
                ToolExecutionDisposition.DELEGATED,
            }:
                raise ValueError("only a claimed tool execution can be delegated")
            key = (claim.lease.task_id, claim.tool_call_id)
            current = self.tool_claims.get(key)
            if current is None or not self._claim_matches_current_fencing(
                current[0], claim
            ):
                raise StaleExecutionLease(claim.lease.task_id)
            result = {
                "child_run_id": child_run_id,
                "child_checkpoint_id": child_checkpoint_id,
            }
            self.tool_claims[key] = (
                ToolExecutionClaim(
                    ToolExecutionDisposition.DELEGATED,
                    claim.tool_call_id,
                    claim.lease,
                    result,
                ),
                claim_expires_at,
            )

    async def request_tool_approval(
        self,
        *,
        lease,
        tool_call,
        validated,
        loop_state,
        workspace_revision,
        requested_at,
        expires_at,
    ):
        async with self._durability_lock:
            self._require_current_lease(lease, now=requested_at)
            canonical = self._canonical_run(lease.task_id)
            if (
                canonical is None
                or canonical.run_id != lease.run_id
                or canonical.status is not CodingRunStatus.RUNNING
            ):
                raise StaleExecutionLease(lease.task_id)
            key = (lease.task_id, lease.run_id, tool_call.tool_call_id)
            existing = self.approvals.get(key)
            if existing is not None:
                expected = canonical_approval_hash(
                    {
                        "task_id": lease.task_id,
                        "run_id": lease.run_id,
                        "tool_call_id": tool_call.tool_call_id,
                        "tool_name": validated.name,
                        "normalized_input": dict(validated.input),
                        "checkpoint_id": existing.checkpoint_id,
                        "workspace_revision": workspace_revision,
                    }
                )
                if existing.request_hash != expected:
                    raise ApprovalConflict("approval_request_mismatch")
                checkpoint = next(
                    item
                    for item in self.checkpoints
                    if item.checkpoint_id == existing.checkpoint_id
                )
                return ApprovalRequestCommit(existing, checkpoint, (), False)
            self._durability_seq += 1
            checkpoint = CodingCheckpoint(
                checkpoint_id=f"cc_approval_{tool_call.tool_call_id}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                seq=self._durability_seq,
                loop_state=dict(loop_state),
                workspace_revision=workspace_revision,
                created_at=requested_at,
            )
            request_hash = canonical_approval_hash(
                {
                    "task_id": lease.task_id,
                    "run_id": lease.run_id,
                    "tool_call_id": tool_call.tool_call_id,
                    "tool_name": validated.name,
                    "normalized_input": dict(validated.input),
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "workspace_revision": workspace_revision,
                }
            )
            approval = CodingApproval(
                approval_id=f"ca_{tool_call.tool_call_id}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                tool_call_id=tool_call.tool_call_id,
                checkpoint_id=checkpoint.checkpoint_id,
                tool_name=validated.name,
                risk=validated.risk,
                workspace_revision=workspace_revision,
                request_hash=request_hash,
                display_summary=approval_display_summary(validated),
                status=ApprovalStatus.PENDING,
                requested_by="test-owner",
                requested_at=requested_at,
                expires_at=expires_at,
            )
            requested_event = make_event(
                task_id=lease.task_id,
                seq=self._durability_seq,
                event_type="approval.requested",
                payload={
                    "approval_id": approval.approval_id,
                    "tool_name": approval.tool_name,
                    "risk": approval.risk.value,
                    "status": approval.status.value,
                    "requested_at": requested_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "display_summary": dict(approval.display_summary),
                },
                now=requested_at,
                run_id=lease.run_id,
                tool_call_id=tool_call.tool_call_id,
                checkpoint_id=checkpoint.checkpoint_id,
            )
            self._durability_seq += 1
            status_event = make_event(
                task_id=lease.task_id,
                seq=self._durability_seq,
                event_type="task.status.changed",
                payload={"status": "waiting_approval"},
                now=requested_at,
                run_id=lease.run_id,
                checkpoint_id=checkpoint.checkpoint_id,
            )
            self.checkpoints.append(checkpoint)
            self.approvals[key] = approval
            self.task_statuses[lease.task_id] = "waiting_approval"
            return ApprovalRequestCommit(
                approval, checkpoint, (requested_event, status_event), True
            )

    async def get_tool_approval(self, *, task_id, run_id, tool_call_id):
        async with self._durability_lock:
            return self.approvals.get((task_id, run_id, tool_call_id))

    async def resolve_tool_approval(
        self, *, task_id, approval_id, owner_id, decision, now, answers=(), remember=False
    ):
        async with self._durability_lock:
            item = next(
                (
                    (key, approval)
                    for key, approval in self.approvals.items()
                    if approval.task_id == task_id
                    and approval.approval_id == approval_id
                    and approval.requested_by == owner_id
                ),
                None,
            )
            if item is None:
                raise ApprovalNotFound(approval_id)
            key, approval = item
            if approval.status is not ApprovalStatus.PENDING:
                raise ApprovalConflict("approval_already_resolved")
            conflict_code = None
            if approval.expires_at <= now:
                status = ApprovalStatus.EXPIRED
                resolved = replace(
                    approval,
                    status=status,
                    decided_at=now,
                )
                conflict_code = "approval_expired"
            elif (
                decision is ApprovalDecision.APPROVE
                and requires_approval_answers(approval.tool_name)
                and not answers
            ):
                raise ApprovalConflict("answers_required")
            elif decision is ApprovalDecision.APPROVE:
                status = ApprovalStatus.APPROVED
                summary = dict(approval.display_summary)
                if answers:
                    summary["answers"] = list(answers)
                if remember:
                    summary["remember"] = True
                resolved = replace(
                    approval,
                    status=status,
                    decision=decision,
                    decided_by=owner_id,
                    decided_at=now,
                    display_summary=summary,
                )
            else:
                status = ApprovalStatus.DENIED
                resolved = replace(
                    approval,
                    status=status,
                    decision=decision,
                    decided_by=owner_id,
                    decided_at=now,
                )
            self._durability_seq += 1
            resolution_event = make_event(
                task_id=task_id,
                seq=self._durability_seq,
                event_type=f"approval.{status.value}",
                payload={
                    "approval_id": approval_id,
                    "tool_name": approval.tool_name,
                    "risk": approval.risk.value,
                    "status": status.value,
                    "requested_at": approval.requested_at.isoformat(),
                    "expires_at": approval.expires_at.isoformat(),
                    "display_summary": dict(resolved.display_summary),
                },
                now=now,
                run_id=approval.run_id,
                tool_call_id=approval.tool_call_id,
                checkpoint_id=approval.checkpoint_id,
            )
            self._durability_seq += 1
            status_event = make_event(
                task_id=task_id,
                seq=self._durability_seq,
                event_type="task.status.changed",
                payload={"status": "running"},
                now=now,
                run_id=approval.run_id,
                checkpoint_id=approval.checkpoint_id,
            )
            self.approvals[key] = resolved
            self.task_statuses[task_id] = "running"
            return ApprovalResolutionCommit(
                resolved,
                (resolution_event, status_event),
                conflict_code,
            )

    async def expire_pending_approvals(self, *, limit, now):
        if limit < 1:
            raise ValueError("limit must be positive")
        pending = sorted(
            (
                approval
                for approval in self.approvals.values()
                if approval.status is ApprovalStatus.PENDING
                and approval.expires_at <= now
            ),
            key=lambda approval: (approval.expires_at, approval.approval_id),
        )[:limit]
        commits = []
        for approval in pending:
            commits.append(
                await self.resolve_tool_approval(
                    task_id=approval.task_id,
                    approval_id=approval.approval_id,
                    owner_id=approval.requested_by,
                    decision=ApprovalDecision.DENY,
                    now=now,
                )
            )
        return tuple(commits)

    def _claim_matches_current_fencing(self, stored, claim) -> bool:
        stored_lease = getattr(stored, "lease", None)
        if stored_lease is None:
            return stored == claim
        return (
            stored_lease.task_id == claim.lease.task_id
            and getattr(stored, "tool_call_id", None) == claim.tool_call_id
            and stored_lease.worker_id == claim.lease.worker_id
            and stored_lease.fencing_token == claim.lease.fencing_token
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

    def _require_canonical_running_run(self, lease) -> None:
        run = self._canonical_run(lease.task_id)
        if (
            run is None
            or run.run_id != lease.run_id
            or run.status is not CodingRunStatus.RUNNING
            or self.task_statuses.get(lease.task_id) != "running"
        ):
            raise StaleExecutionLease(lease.task_id)

    async def start_model_text_part(self, *, lease, part_id, turn_id, now):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            self._require_canonical_running_run(lease)
            if part_id in self.text_parts or any(
                part.task_id == lease.task_id and part.turn_id == turn_id
                for part in self.text_parts.values()
            ):
                raise TextPartConflict("model_text_part_exists")
            self._durability_seq += 1
            seq = self._durability_seq
            interrupted_ids = tuple(
                sorted(
                    part.part_id
                    for part in self.text_parts.values()
                    if part.task_id == lease.task_id
                    and part.run_id == lease.run_id
                    and part.status is TextPartStatus.STREAMING
                )
            )
            for interrupted_id in interrupted_ids:
                self.text_parts[interrupted_id] = replace(
                    self.text_parts[interrupted_id],
                    status=TextPartStatus.INTERRUPTED,
                    last_seq=seq,
                    updated_at=now,
                )
            part = CodingTextPart(
                part_id=part_id,
                task_id=lease.task_id,
                run_id=lease.run_id,
                turn_id=turn_id,
                first_seq=seq,
                last_seq=seq,
                status=TextPartStatus.STREAMING,
                content="",
                content_bytes=0,
                created_at=now,
                updated_at=now,
            )
            self.text_parts[part_id] = part
            event = make_event(
                task_id=lease.task_id,
                seq=seq,
                event_type="model.text_part.started",
                payload={
                    "part_id": part_id,
                    "status": TextPartStatus.STREAMING.value,
                    "interrupted_part_ids": list(interrupted_ids),
                },
                now=now,
                run_id=lease.run_id,
                turn_id=turn_id,
            )
            return ModelTextPartCommit(part, event, interrupted_ids)

    async def append_model_text_delta(
        self,
        *,
        lease,
        part_id,
        turn_id,
        delta,
        delta_bytes,
        max_part_bytes,
        now,
    ):
        if not delta or delta_bytes != len(delta.encode("utf-8")):
            raise ValueError("delta_bytes must match a non-empty UTF-8 delta")
        if max_part_bytes < 1:
            raise ValueError("max_part_bytes must be positive")
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            self._require_canonical_running_run(lease)
            part = self.text_parts.get(part_id)
            if (
                part is None
                or part.task_id != lease.task_id
                or part.run_id != lease.run_id
                or part.turn_id != turn_id
                or part.status is not TextPartStatus.STREAMING
            ):
                raise TextPartConflict("model_text_part_stale")
            if part.content_bytes + delta_bytes > max_part_bytes:
                raise TextPartConflict("model_public_text_budget_exceeded")
            self._durability_seq += 1
            seq = self._durability_seq
            updated = replace(
                part,
                content=part.content + delta,
                content_bytes=part.content_bytes + delta_bytes,
                last_seq=seq,
                updated_at=now,
            )
            self.text_parts[part_id] = updated
            event = make_event(
                task_id=lease.task_id,
                seq=seq,
                event_type="model.text_delta",
                payload={"part_id": part_id, "delta": delta},
                now=now,
                run_id=lease.run_id,
                turn_id=turn_id,
            )
            return ModelTextPartCommit(updated, event)

    async def complete_model_text_part(self, *, lease, part_id, turn_id, now):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            self._require_canonical_running_run(lease)
            part = self.text_parts.get(part_id)
            if (
                part is None
                or part.task_id != lease.task_id
                or part.run_id != lease.run_id
                or part.turn_id != turn_id
                or part.status is not TextPartStatus.STREAMING
            ):
                raise TextPartConflict("model_text_part_stale")
            self._durability_seq += 1
            seq = self._durability_seq
            completed = replace(
                part,
                status=TextPartStatus.COMPLETED,
                last_seq=seq,
                updated_at=now,
            )
            self.text_parts[part_id] = completed
            event = make_event(
                task_id=lease.task_id,
                seq=seq,
                event_type="model.text_part.completed",
                payload={"part_id": part_id, "status": "completed"},
                now=now,
                run_id=lease.run_id,
                turn_id=turn_id,
            )
            return ModelTextPartCommit(completed, event)

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

    async def commit_model_checkpoint(
        self,
        *,
        lease,
        event_type,
        event_payload,
        loop_state,
        workspace_revision,
        now,
    ):
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            self.model_commit_calls += 1
            self._durability_seq += 1
            checkpoint = CodingCheckpoint(
                checkpoint_id=f"cc_model_{self._durability_seq}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                seq=self._durability_seq,
                loop_state=dict(loop_state),
                workspace_revision=workspace_revision,
                created_at=now,
            )
            self.checkpoints.append(checkpoint)
            event = make_event(
                task_id=lease.task_id,
                seq=checkpoint.seq,
                event_type=event_type,
                payload=dict(event_payload),
                now=now,
                run_id=lease.run_id,
                checkpoint_id=checkpoint.checkpoint_id,
            )
            return ModelCheckpointCommit(checkpoint, event)

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

    async def has_pending_interrupt(self, task_id: str) -> bool:
        return any(
            item.task_id == task_id
            and item.mode in {SteeringMode.INTERRUPT_NOW, SteeringMode.CANCEL}
            and item not in self.applied_steering
            for item in self.steering_requests
        )

    async def claim_pending_interrupt(self, task_id: str):
        for request in self.steering_requests:
            if (
                request.task_id == task_id
                and request.mode in {SteeringMode.INTERRUPT_NOW, SteeringMode.CANCEL}
                and request not in self.applied_steering
            ):
                return request
        return None

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
            loop_state["pending_instruction"] = request.instruction
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

    async def claim_workspace_edits_at_safe_point(
        self,
        *,
        lease,
        checkpoint,
        limit,
        now,
    ):
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._durability_lock:
            self._require_current_lease(lease, now=now)
            candidates = sorted(
                (
                    edit
                    for edit in self.workspace_edits.values()
                    if edit.task_id == lease.task_id
                    and edit.status is WorkspaceEditStatus.COMMITTED
                ),
                key=lambda edit: (
                    int(edit.resulting_revision or "0"),
                    edit.edit_id,
                ),
            )[:limit]
            if not candidates:
                return None
            contexts = [
                {
                    "edit_id": edit.edit_id,
                    "path": edit.path,
                    "resulting_revision": edit.resulting_revision,
                }
                for edit in candidates
            ]
            self._durability_seq += len(candidates)
            applied_checkpoint = CodingCheckpoint(
                checkpoint_id=f"cc_workspace_{self._durability_seq}",
                task_id=lease.task_id,
                run_id=lease.run_id,
                seq=self._durability_seq,
                loop_state={
                    **dict(checkpoint.loop_state),
                    "pending_workspace_edits": contexts,
                },
                workspace_revision=checkpoint.workspace_revision,
                created_at=now,
            )
            applied = []
            events = []
            first_seq = self._durability_seq - len(candidates) + 1
            for offset, edit in enumerate(candidates):
                value = replace(
                    edit,
                    status=WorkspaceEditStatus.APPLIED,
                    applied_checkpoint_id=applied_checkpoint.checkpoint_id,
                )
                self.workspace_edits[value.edit_id] = value
                applied.append(value)
                events.append(
                    make_event(
                        task_id=lease.task_id,
                        seq=first_seq + offset,
                        event_type="workspace.user_edit.synced",
                        payload={
                            "edit_id": value.edit_id,
                            "path": value.path,
                            "resulting_revision": value.resulting_revision,
                            "status": "agent_synced",
                            "applied_checkpoint_id": (
                                applied_checkpoint.checkpoint_id
                            ),
                        },
                        now=now,
                        run_id=lease.run_id,
                        checkpoint_id=applied_checkpoint.checkpoint_id,
                    )
                )
            self.checkpoints.append(applied_checkpoint)
            return WorkspaceEditApplication(
                tuple(applied),
                applied_checkpoint,
                tuple(events),
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
            applied = replace(request, applied_checkpoint_id=checkpoint.checkpoint_id)
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
            existing for existing in self.phases if existing.phase_id != phase.phase_id
        ]
        self.phases.append(phase)
