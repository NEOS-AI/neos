from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, Protocol

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint, CodingPhase, CodingPhaseKind


@dataclass(frozen=True, slots=True)
class LoopInput:
    task_id: str
    run_id: str
    instruction: str


@dataclass(frozen=True, slots=True)
class LoopCheckpointState:
    phase_index: int
    transcript: tuple[Mapping[str, object], ...]
    pending_instruction: str | None
    workspace_revision: str


class CodingRunRepository(Protocol):
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


class CodingLoop(Protocol):
    def run(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]: ...
