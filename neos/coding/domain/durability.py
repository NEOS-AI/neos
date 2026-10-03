from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhase,
    CodingRun,
    SteeringRequest,
)


class RunAlreadyLeased(RuntimeError):
    pass


class StaleExecutionLease(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunLifecycleCommit:
    run: CodingRun
    event: CodingEvent


class TaskPaused(RuntimeError):
    """The task is `paused` -- no worker may advance it until a person resumes it
    (track Q10b). Raised instead of returning `None`, which means "completed"."""


#: `task.status.changed` 의 `status` 값. 루프가 멈춤을 커밋했다는 신호이기도 하다.
PAUSED_STATUS = "paused"


@dataclass(frozen=True, slots=True)
class TaskPauseCommit:
    """One transaction: the judgement that paused the task, then the status change.

    The run stays `running` -- like `waiting_approval`, the task is what stops,
    and resuming continues the same run from its latest checkpoint.
    """

    events: tuple[CodingEvent, ...]

    @property
    def status_event(self) -> CodingEvent:
        return self.events[-1]


@dataclass(frozen=True, slots=True)
class TaskResumeCommit:
    """`paused -> running`, and the checkpoint the woken worker should expect."""

    event: CodingEvent
    checkpoint_id: str | None


def is_pause_event(event: Any) -> bool:
    """The event a paused loop hands back to the run service."""
    return (
        getattr(event, "type", None) == "task.status.changed"
        and (getattr(event, "payload", None) or {}).get("status") == PAUSED_STATUS
    )


class ToolExecutionDisposition(StrEnum):
    CLAIMED = "claimed"
    RECLAIMED = "reclaimed"
    COMPLETED = "completed"
    BUSY = "busy"
    DELEGATED = "delegated"


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    task_id: str
    run_id: str
    worker_id: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    recovered: bool = False

    def __post_init__(self) -> None:
        if self.fencing_token < 1:
            raise ValueError("fencing token must be positive")
        if self.expires_at <= self.acquired_at:
            raise ValueError("expires_at must follow acquired_at")


@dataclass(frozen=True, slots=True)
class ToolExecutionClaim:
    disposition: ToolExecutionDisposition
    tool_call_id: str
    lease: ExecutionLease
    result: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PhaseStart:
    phase: CodingPhase
    event: CodingEvent | None
    resumed: bool


@dataclass(frozen=True, slots=True)
class PhaseCheckpointCommit:
    checkpoint: CodingCheckpoint
    event: CodingEvent
    phase: CodingPhase


@dataclass(frozen=True, slots=True)
class ModelCheckpointCommit:
    checkpoint: CodingCheckpoint
    event: CodingEvent


@dataclass(frozen=True, slots=True)
class SteeringApplication:
    request: SteeringRequest
    checkpoint: CodingCheckpoint
    previous_run: CodingRun
    run: CodingRun
    lease: ExecutionLease
    event: CodingEvent
