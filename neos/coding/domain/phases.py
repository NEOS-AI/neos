from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Sequence


class CodingPhaseKind(StrEnum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    REVIEW = "review"


class CodingPhaseStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class CodingRunStatus(StrEnum):
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SteeringMode(StrEnum):
    SAFE_POINT = "safe_point"
    INTERRUPT_NOW = "interrupt_now"


@dataclass(frozen=True, slots=True)
class CodingPhase:
    phase_id: str
    task_id: str
    run_id: str
    kind: CodingPhaseKind
    attempt: int
    status: CodingPhaseStatus
    started_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CodingRun:
    run_id: str
    task_id: str
    attempt: int
    status: CodingRunStatus
    resume_from_checkpoint_id: str | None
    started_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CodingCheckpoint:
    checkpoint_id: str
    task_id: str
    run_id: str
    seq: int
    loop_state: Mapping[str, Any]
    workspace_revision: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SteeringRequest:
    steering_id: str
    task_id: str
    mode: SteeringMode
    instruction: str
    requested_at: datetime
    applied_checkpoint_id: str | None = None


def next_phase_attempt(
    *,
    task_id: str,
    run_id: str,
    kind: CodingPhaseKind,
    existing: Sequence[tuple[CodingPhaseKind, int]],
    now: datetime,
) -> CodingPhase:
    attempts = [attempt for phase_kind, attempt in existing if phase_kind is kind]
    if any(attempt < 1 for attempt in attempts):
        raise ValueError("phase attempt must be positive")
    attempt = max(attempts, default=0) + 1
    return CodingPhase(
        phase_id=f"cp_{run_id}_{kind.value}_{attempt}",
        task_id=task_id,
        run_id=run_id,
        kind=kind,
        attempt=attempt,
        status=CodingPhaseStatus.ACTIVE,
        started_at=now,
    )
