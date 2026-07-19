from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from uuid import uuid4

from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)


@dataclass(frozen=True, slots=True)
class InterruptionResult:
    workspace_revision: str
    process_stopped: bool


class RunInterrupter(Protocol):
    async def interrupt(self, run_id: str) -> InterruptionResult: ...


class InProcessRunInterrupter:
    async def interrupt(self, run_id: str) -> InterruptionResult:
        return InterruptionResult(
            workspace_revision=f"fake-interrupt:{run_id}",
            process_stopped=True,
        )


class CodingRunService:
    def __init__(
        self,
        *,
        tasks,
        runs,
        events,
        interrupter: RunInterrupter,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._tasks = tasks
        self._runs = runs
        self._events = events
        self._interrupter = interrupter
        self._clock = clock

    async def start(self, *, task_id: str, instruction: str) -> CodingRun:
        previous = await self._runs.latest_run(task_id)
        run = CodingRun(
            run_id=f"cr_{uuid4().hex}",
            task_id=task_id,
            attempt=(previous.attempt + 1) if previous else 1,
            status=CodingRunStatus.RUNNING,
            resume_from_checkpoint_id=(
                previous.resume_from_checkpoint_id if previous else None
            ),
            started_at=self._clock(),
        )
        await self._runs.create_run(run)
        await self._append(
            task_id=task_id,
            event_type="run.started",
            payload={"instruction": instruction, "attempt": run.attempt},
            run_id=run.run_id,
        )
        return run

    async def steer(
        self,
        *,
        task_id: str,
        owner_id: str,
        instruction: str,
        mode: SteeringMode,
    ) -> SteeringRequest:
        if await self._tasks.get_owned(task_id, owner_id) is None:
            raise CodingTaskNotFound(task_id)
        request = SteeringRequest(
            steering_id=f"cs_{uuid4().hex}",
            task_id=task_id,
            mode=mode,
            instruction=instruction,
            requested_at=self._clock(),
        )
        await self._runs.queue_steering(request)
        await self._append(
            task_id=task_id,
            event_type="steer.queued",
            payload={"steering_id": request.steering_id, "mode": mode.value},
        )
        if mode is SteeringMode.INTERRUPT_NOW:
            await self._interrupt_active_run(task_id, request)
        return request

    async def on_safe_point(self, *, task_id: str, checkpoint_id: str) -> None:
        request = await self._runs.claim_pending_steering(task_id)
        if request is None or request.mode is not SteeringMode.SAFE_POINT:
            return
        applied = replace(request, applied_checkpoint_id=checkpoint_id)
        await self._runs.apply_steering(applied)
        await self._append(
            task_id=task_id,
            event_type="steer.applied",
            payload={
                "steering_id": request.steering_id,
                "instruction": request.instruction,
            },
            checkpoint_id=checkpoint_id,
        )

    async def stop(self, *, task_id: str) -> None:
        run = await self._runs.latest_run(task_id)
        if run is None:
            return
        await self._interrupter.interrupt(run.run_id)
        await self._runs.update_run(
            replace(run, status=CodingRunStatus.CANCELLED, completed_at=self._clock())
        )

    async def _interrupt_active_run(
        self, task_id: str, request: SteeringRequest
    ) -> None:
        run = await self._runs.latest_run(task_id)
        if run is None:
            return
        await self._runs.update_run(
            replace(run, status=CodingRunStatus.INTERRUPTING)
        )
        result = await self._interrupter.interrupt(run.run_id)
        checkpoint_id = f"cc_interrupt_{uuid4().hex}"
        event = await self._append(
            task_id=task_id,
            event_type="run.interrupted",
            payload={
                "steering_id": request.steering_id,
                "process_stopped": result.process_stopped,
            },
            run_id=run.run_id,
            checkpoint_id=checkpoint_id,
        )
        await self._runs.save_checkpoint(
            CodingCheckpoint(
                checkpoint_id=checkpoint_id,
                task_id=task_id,
                run_id=run.run_id,
                seq=event.seq,
                loop_state={
                    "phase_index": -1,
                    "transcript": [],
                    "pending_instruction": request.instruction,
                },
                workspace_revision=result.workspace_revision,
                created_at=self._clock(),
            )
        )
        await self._runs.update_run(
            replace(run, status=CodingRunStatus.CANCELLED, completed_at=self._clock())
        )
        await self._runs.apply_steering(
            replace(request, applied_checkpoint_id=checkpoint_id)
        )
        resumed = CodingRun(
            run_id=f"cr_{uuid4().hex}",
            task_id=task_id,
            attempt=run.attempt + 1,
            status=CodingRunStatus.RUNNING,
            resume_from_checkpoint_id=checkpoint_id,
            started_at=self._clock(),
        )
        await self._runs.create_run(resumed)

    async def _append(self, **kwargs: Any):
        return await self._events.append(now=self._clock(), **kwargs)
