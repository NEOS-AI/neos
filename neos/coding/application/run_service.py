import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4


from neos.coding.domain.durability import (
    RunAlreadyLeased,
    StaleExecutionLease,
)
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
from neos.coding.loop.base import (
    CodingLoop,
    LoopDependencies,
    LoopInput,
    WorkspaceEditContext,
)


_EXPECTED_CHECKPOINT_OMITTED = object()


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
        loop: CodingLoop | None = None,
        metrics=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        execution_lease: timedelta = timedelta(seconds=30),
        workspace_edit_batch_size: int = 20,
    ) -> None:
        if execution_lease.total_seconds() <= 0:
            raise ValueError("execution_lease must be positive")
        if workspace_edit_batch_size < 1:
            raise ValueError("workspace_edit_batch_size must be positive")
        self._tasks = tasks
        self._runs = runs
        self._events = events
        self._interrupter = interrupter
        self._loop = loop
        self._metrics = metrics
        self._clock = clock
        self._execution_lease = execution_lease
        self._workspace_edit_batch_size = workspace_edit_batch_size

    async def ensure_started(self, *, task_id: str) -> CodingRun:
        task = await self._tasks.get(task_id)
        if task is None:
            raise CodingTaskNotFound(task_id)
        return await self._runs.ensure_run_started(
            task_id=task_id,
            instruction=task.prompt,
            development_mode=True,
            now=self._clock(),
        )

    async def fail_active_run(
        self,
        *,
        task_id: str,
        worker_id: str,
        error_code: str,
    ):
        run = await self._runs.latest_run(task_id)
        if run is None:
            raise RuntimeError(f"coding run does not exist: {task_id}")
        now = self._clock()
        lease = await self._runs.acquire_execution_lease(
            task_id=task_id,
            run_id=run.run_id,
            worker_id=worker_id,
            now=now,
            expires_at=now + self._execution_lease,
        )
        if lease is None:
            raise RunAlreadyLeased(task_id)
        try:
            committed = await self._runs.fail_run(
                lease=lease,
                error_code=error_code,
                now=now,
            )
        except Exception:
            await self._release_lease(lease)
            raise
        await self._release_lease(lease)
        return committed.event

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

    async def advance_one_safe_point(
        self,
        *,
        task_id: str,
        worker_id: str,
        expected_checkpoint_id: str | None | object = _EXPECTED_CHECKPOINT_OMITTED,
    ):
        """Advance a durable loop from its latest committed checkpoint.

        The iterator is intentionally rebuilt for every call. A replacement
        worker therefore follows the same path as the original process after a
        crash and relies only on persisted checkpoints and tool results.
        """
        if self._loop is None:
            raise RuntimeError("coding loop is not configured")
        run = await self._runs.latest_run(task_id)
        if run is None:
            raise RuntimeError(f"coding run does not exist: {task_id}")
        now = self._clock()
        lease_kwargs = dict(
            task_id=task_id,
            run_id=run.run_id,
            worker_id=worker_id,
            now=now,
            expires_at=now + self._execution_lease,
        )
        if expected_checkpoint_id is not _EXPECTED_CHECKPOINT_OMITTED:
            lease_kwargs["expected_checkpoint_id"] = expected_checkpoint_id
        lease = await self._runs.acquire_execution_lease(**lease_kwargs)
        if lease is None:
            if self._metrics is not None:
                self._metrics.coding_lease_contention_total.labels(outcome="busy").inc()
            raise RunAlreadyLeased(task_id)
        if self._metrics is not None:
            self._metrics.coding_lease_contention_total.labels(outcome="acquired").inc()
        checkpoint = await self._runs.latest_checkpoint(task_id)
        if checkpoint is not None:
            applied = await self.on_safe_point(
                task_id=task_id,
                checkpoint_id=checkpoint.checkpoint_id,
                lease=lease,
                checkpoint=checkpoint,
                worker_id=worker_id,
            )
            if applied:
                checkpoint = applied.checkpoint
                run = applied.run
                lease = applied.lease
            workspace_application = (
                await self._runs.claim_workspace_edits_at_safe_point(
                    lease=lease,
                    checkpoint=checkpoint,
                    limit=self._workspace_edit_batch_size,
                    now=self._clock(),
                )
            )
            if workspace_application is not None:
                checkpoint = workspace_application.checkpoint

        if checkpoint is not None:
            instruction = str(checkpoint.loop_state["current_instruction"])
        else:
            task = await self._tasks.get(task_id)
            if task is None:
                raise CodingTaskNotFound(task_id)
            instruction = task.prompt
        stream = self._loop.run(
            LoopInput(
                task_id=task_id,
                run_id=run.run_id,
                instruction=instruction,
                workspace_edits=self._workspace_edit_contexts(checkpoint),
            ),
            checkpoint,
            LoopDependencies(
                repository=self._runs,
                events=self._events,
                lease=lease,
            ),
        )
        phase_started: dict[str, datetime] = {}
        try:
            async for event in stream:
                if event.type == "phase.started":
                    phase_started[str(event.payload["phase"])] = event.created_at
                if event.type == "phase.completed":
                    phase = str(event.payload["phase"])
                    if self._metrics is not None:
                        started = phase_started.get(phase, event.created_at)
                        duration = max(
                            0.0, (event.created_at - started).total_seconds()
                        )
                        self._metrics.coding_phase_duration_seconds.labels(
                            phase=phase
                        ).observe(duration)
                        self._metrics.coding_checkpoint_total.labels(phase=phase).inc()
                        if lease.recovered:
                            self._metrics.coding_resume_total.labels(
                                outcome="success"
                            ).inc()
                    await self._release_lease(lease)
                    return event
                if event.type == "run.completed":
                    await self._runs.update_run(
                        replace(
                            run,
                            status=CodingRunStatus.COMPLETED,
                            completed_at=self._clock(),
                        )
                    )
                    await self._release_lease(lease)
                    return event
                if event.checkpoint_id is not None:
                    await self._release_lease(lease)
                    return event
            committed = await self._runs.complete_run(lease=lease, now=self._clock())
            await self._release_lease(lease)
            return committed.event
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._metrics is not None and lease.recovered:
                self._metrics.coding_resume_total.labels(
                    outcome="recovery_required"
                ).inc()
            await self._release_lease(lease)
            raise
        return None

    @staticmethod
    def _workspace_edit_contexts(
        checkpoint: CodingCheckpoint | None,
    ) -> tuple[WorkspaceEditContext, ...]:
        if checkpoint is None:
            return ()
        raw = checkpoint.loop_state.get("pending_workspace_edits", ())
        return tuple(
            WorkspaceEditContext(
                edit_id=str(item["edit_id"]),
                path=str(item["path"]),
                resulting_revision=str(item["resulting_revision"]),
            )
            for item in raw
        )

    async def advance_until(self, *, task_id: str, phase: str, worker_id: str):
        while True:
            event = await self.advance_one_safe_point(
                task_id=task_id, worker_id=worker_id
            )
            if event is None or event.type == "run.completed":
                return event
            if event.payload.get("phase") == phase:
                return event

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
            run = await self._runs.latest_run(task_id)
            if run is not None:
                now = self._clock()
                lease = await self._runs.acquire_execution_lease(
                    task_id=task_id,
                    run_id=run.run_id,
                    worker_id=f"interrupt:{request.steering_id}",
                    now=now,
                    expires_at=now + self._execution_lease,
                )
                if lease is None:
                    if self._metrics is not None:
                        self._metrics.coding_lease_contention_total.labels(
                            outcome="busy"
                        ).inc()
                    raise RunAlreadyLeased(task_id)
                await self._interrupt_active_run(task_id, request, lease)
        return request

    async def on_safe_point(
        self,
        *,
        task_id: str,
        checkpoint_id: str,
        lease=None,
        checkpoint: CodingCheckpoint | None = None,
        worker_id: str | None = None,
    ):
        if lease is not None:
            if checkpoint is None:
                raise ValueError("checkpoint is required for atomic steering")
            now = self._clock()
            applied = await self._runs.apply_steering_at_safe_point(
                lease=lease,
                checkpoint=checkpoint,
                worker_id=worker_id or lease.worker_id,
                claim_expires_at=now + timedelta(seconds=30),
                now=now,
            )
            if applied is None:
                return False
            if self._metrics is not None:
                latency = max(
                    0.0,
                    (now - applied.request.requested_at).total_seconds(),
                )
                self._metrics.coding_steering_latency_seconds.labels(
                    outcome="applied"
                ).observe(latency)
            return applied
        request = await self._runs.claim_pending_steering(task_id)
        if request is None or request.mode is not SteeringMode.SAFE_POINT:
            return False
        run = await self._runs.latest_run(task_id)
        if run is None:
            await self._runs.apply_steering(
                replace(request, applied_checkpoint_id=checkpoint_id)
            )
            await self._append(
                task_id=task_id,
                event_type="steer.applied",
                payload={
                    "steering_id": request.steering_id,
                    "instruction": request.instruction,
                },
                checkpoint_id=checkpoint_id,
            )
            return True
        steering_checkpoint_id = f"cc_steer_{uuid4().hex}"
        event = await self._append(
            task_id=task_id,
            event_type="steer.applied",
            payload={
                "steering_id": request.steering_id,
                "instruction": request.instruction,
            },
            checkpoint_id=steering_checkpoint_id,
        )
        await self._runs.save_checkpoint(
            CodingCheckpoint(
                checkpoint_id=steering_checkpoint_id,
                task_id=task_id,
                run_id=run.run_id,
                seq=event.seq,
                loop_state={
                    "phase_index": -1,
                    "transcript": [],
                    "pending_instruction": request.instruction,
                },
                workspace_revision=f"fake-steer:{checkpoint_id}",
                created_at=self._clock(),
            )
        )
        applied = replace(request, applied_checkpoint_id=steering_checkpoint_id)
        await self._runs.apply_steering(applied)
        if self._metrics is not None:
            latency = max(0.0, (self._clock() - request.requested_at).total_seconds())
            self._metrics.coding_steering_latency_seconds.labels(
                outcome="applied"
            ).observe(latency)
        await self._runs.update_run(
            replace(
                run,
                status=CodingRunStatus.CANCELLED,
                completed_at=self._clock(),
            )
        )
        await self._runs.create_run(
            CodingRun(
                run_id=f"cr_{uuid4().hex}",
                task_id=task_id,
                attempt=run.attempt + 1,
                status=CodingRunStatus.RUNNING,
                resume_from_checkpoint_id=steering_checkpoint_id,
                started_at=self._clock(),
            )
        )
        return True

    async def stop(self, *, task_id: str) -> None:
        run = await self._runs.latest_run(task_id)
        if run is None:
            return
        await self._interrupter.interrupt(run.run_id)
        await self._runs.update_run(
            replace(run, status=CodingRunStatus.CANCELLED, completed_at=self._clock())
        )

    async def _interrupt_active_run(self, task_id, request, lease) -> None:
        run = await self._runs.latest_run(task_id)
        if run is None:
            await self._release_lease(lease)
            return
        try:
            result = await self._interrupter.interrupt(run.run_id)
        except Exception:
            await self._release_lease(lease)
            raise
        if not result.process_stopped:
            await self._release_lease(lease)
            raise RuntimeError("coding run process did not stop")
        applied = await self._runs.commit_interruption(
            lease=lease,
            request=request,
            workspace_revision=result.workspace_revision,
            process_stopped=result.process_stopped,
            now=self._clock(),
        )
        await self._release_lease(applied.lease)

    async def _append(self, **kwargs: Any):
        return await self._events.append(now=self._clock(), **kwargs)

    async def _release_lease(self, lease) -> None:
        try:
            await self._runs.release_execution_lease(lease, now=self._clock())
        except StaleExecutionLease:
            if self._metrics is not None:
                self._metrics.coding_lease_contention_total.labels(
                    outcome="stale_write"
                ).inc()
            raise
