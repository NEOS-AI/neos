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


class ToolExecutionDisposition(StrEnum):
    CLAIMED = "claimed"
    COMPLETED = "completed"
    BUSY = "busy"


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
class SteeringApplication:
    request: SteeringRequest
    checkpoint: CodingCheckpoint
    previous_run: CodingRun
    run: CodingRun
    lease: ExecutionLease
    event: CodingEvent
