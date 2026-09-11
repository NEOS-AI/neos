from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Mapping, Protocol

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.text_parts import ModelTextPartCommit
from neos.coding.domain.approvals import (
    ApprovalDecision,
    ApprovalRequestCommit,
    ApprovalResolutionCommit,
    CodingApproval,
)
from neos.coding.domain.durability import (
    ExecutionLease,
    ModelCheckpointCommit,
    PhaseCheckpointCommit,
    PhaseStart,
    RunLifecycleCommit,
    SteeringApplication,
    ToolExecutionClaim,
)
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhase,
    CodingPhaseKind,
    SteeringRequest,
)
from neos.coding.model.base import ToolCallCompleted
from neos.coding.tools.registry import ValidatedToolCall


EXPECTED_CHECKPOINT_OMITTED = object()


@dataclass(frozen=True, slots=True)
class WorkspaceEditContext:
    edit_id: str
    path: str
    resulting_revision: str


@dataclass(frozen=True, slots=True)
class LoopInput:
    task_id: str
    run_id: str
    instruction: str
    workspace_edits: tuple[WorkspaceEditContext, ...] = ()
    owner_id: str | None = None


@dataclass(frozen=True, slots=True)
class LoopCheckpointState:
    phase_index: int
    transcript: tuple[Mapping[str, object], ...]
    pending_instruction: str | None
    workspace_revision: str


class CodingRunRepository(Protocol):
    async def ensure_run_started(
        self,
        *,
        task_id: str,
        instruction: str,
        development_mode: bool,
        now: datetime,
    ): ...

    async def complete_run(
        self, *, lease: ExecutionLease, now: datetime
    ) -> RunLifecycleCommit: ...

    async def fail_run(
        self,
        *,
        lease: ExecutionLease,
        error_code: str,
        now: datetime,
    ) -> RunLifecycleCommit: ...

    async def claimable_task_ids(self, *, limit: int) -> tuple[str, ...]: ...

    async def claimable_delivery_tokens(
        self, *, limit: int
    ) -> tuple[tuple[str, str | None], ...]: ...

    async def acquire_execution_lease(
        self,
        *,
        task_id: str,
        run_id: str,
        worker_id: str,
        now: datetime,
        expires_at: datetime,
        expected_checkpoint_id: str | None | object = EXPECTED_CHECKPOINT_OMITTED,
    ) -> ExecutionLease | None: ...

    async def renew_execution_lease(
        self,
        lease: ExecutionLease,
        *,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionLease: ...

    async def release_execution_lease(
        self, lease: ExecutionLease, *, now: datetime
    ) -> None: ...

    async def claim_tool_execution(
        self,
        *,
        lease: ExecutionLease,
        tool_call_id: str,
        now: datetime,
        claim_expires_at: datetime,
    ) -> ToolExecutionClaim: ...

    async def complete_tool_execution(
        self,
        claim: ToolExecutionClaim,
        *,
        result: Mapping[str, Any],
        now: datetime,
    ) -> CodingEvent: ...

    async def request_tool_approval(
        self,
        *,
        lease: ExecutionLease,
        tool_call: ToolCallCompleted,
        validated: ValidatedToolCall,
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ApprovalRequestCommit: ...

    async def get_tool_approval(
        self, *, task_id: str, run_id: str, tool_call_id: str
    ) -> CodingApproval | None: ...

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

    async def begin_phase(
        self,
        *,
        lease: ExecutionLease,
        kind: CodingPhaseKind,
        now: datetime,
    ) -> PhaseStart: ...

    async def commit_phase_checkpoint(
        self,
        *,
        lease: ExecutionLease,
        phase: CodingPhase,
        tool_call_id: str,
        result: Mapping[str, Any],
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        now: datetime,
    ) -> PhaseCheckpointCommit: ...

    async def commit_model_checkpoint(
        self,
        *,
        lease: ExecutionLease,
        event_type: str,
        event_payload: Mapping[str, Any],
        loop_state: Mapping[str, Any],
        workspace_revision: str,
        now: datetime,
    ) -> ModelCheckpointCommit: ...

    async def start_model_text_part(
        self,
        *,
        lease: ExecutionLease,
        part_id: str,
        turn_id: str,
        now: datetime,
    ) -> ModelTextPartCommit: ...

    async def append_model_text_delta(
        self,
        *,
        lease: ExecutionLease,
        part_id: str,
        turn_id: str,
        delta: str,
        delta_bytes: int,
        max_part_bytes: int,
        now: datetime,
    ) -> ModelTextPartCommit: ...

    async def complete_model_text_part(
        self,
        *,
        lease: ExecutionLease,
        part_id: str,
        turn_id: str,
        now: datetime,
    ) -> ModelTextPartCommit: ...

    async def apply_steering_at_safe_point(
        self,
        *,
        lease: ExecutionLease,
        checkpoint: CodingCheckpoint,
        worker_id: str,
        claim_expires_at: datetime,
        now: datetime,
    ) -> SteeringApplication | None: ...

    async def claim_workspace_edits_at_safe_point(
        self,
        *,
        lease: ExecutionLease,
        checkpoint: CodingCheckpoint,
        limit: int,
        now: datetime,
    ): ...

    async def commit_interruption(
        self,
        *,
        lease: ExecutionLease,
        request: SteeringRequest,
        workspace_revision: str,
        process_stopped: bool,
        now: datetime,
    ) -> SteeringApplication: ...

    async def completed_tool_result(
        self, task_id: str, tool_call_id: str
    ) -> Mapping[str, Any] | None: ...

    async def record_tool_result(self, **record: Any) -> None: ...

    async def save_checkpoint(self, checkpoint: CodingCheckpoint) -> None: ...

    async def phase_history(
        self, task_id: str
    ) -> tuple[tuple[CodingPhaseKind, int], ...]: ...

    async def save_phase(self, phase: CodingPhase) -> None: ...


class CodingLoopEventSink(Protocol):
    async def append(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        run_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> CodingEvent: ...


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    repository: CodingRunRepository
    events: CodingLoopEventSink
    lease: ExecutionLease | None = None


class CodingLoop(Protocol):
    def run(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]: ...
