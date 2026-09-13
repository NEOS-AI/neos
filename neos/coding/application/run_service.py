import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4


from neos.coding.domain.durability import (
    RunAlreadyLeased,
    StaleExecutionLease,
    SteeringApplication,
    ToolExecutionDisposition,
)
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.models import CodingTaskStatus, TERMINAL_TASK_STATUSES
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
from neos.coding.learn_lessons import stage_coding_lesson
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
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def bind(self, run_id: str, task: asyncio.Task) -> None:
        self._tasks[run_id] = task

    def unbind(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)

    async def interrupt(self, run_id: str) -> InterruptionResult:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
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
            await self._cancel_parent_children(lease, now)
            committed = await self._runs.fail_run(
                lease=lease,
                error_code=error_code,
                now=now,
            )
        except Exception:
            await self._release_lease(lease)
            raise
        await self._release_lease(lease)
        try:
            task = await self._tasks.get(task_id)
            payload = dict(committed.event.payload)
            await stage_coding_lesson(
                owner_id=task.owner_id if task is not None else None,
                task_id=task_id,
                outcome="failed",
                events=(
                    {
                        "type": committed.event.type,
                        "event_type": committed.event.type,
                        "error_code": payload.get("error_code") or error_code,
                        "reason_code": payload.get("reason_code"),
                    },
                ),
            )
        except Exception:
            pass
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
        task = await self._tasks.get(task_id)
        if task is not None and task.status is CodingTaskStatus.CANCELLED:
            committed = await self._cancel_active_run(lease, now)
            await self._release_lease(lease)
            if committed is not None:
                return committed.event
            return await self._append(
                task_id=task_id,
                event_type="run.cancelled",
                payload={"status": "cancelled"},
                run_id=run.run_id,
            )
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
                if getattr(applied, "request", None) is not None and (
                    applied.request.mode is SteeringMode.INTERRUPT_NOW
                    or applied.request.mode is SteeringMode.CANCEL
                ):
                    await self._release_lease(applied.lease)
                    return applied.event
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
            if task is None:
                raise CodingTaskNotFound(task_id)
            instruction = task.prompt
        lease = await self._renew_lease_for_child(lease, checkpoint, self._clock())
        stream = self._loop.run(
            LoopInput(
                task_id=task_id,
                run_id=run.run_id,
                instruction=instruction,
                workspace_edits=self._workspace_edit_contexts(checkpoint),
                owner_id=task.owner_id if task is not None else None,
            ),
            checkpoint,
            LoopDependencies(
                repository=self._runs,
                events=self._events,
                lease=lease,
            ),
        )
        phase_started: dict[str, datetime] = {}
        bind = getattr(self._interrupter, "bind", None)
        unbind = getattr(self._interrupter, "unbind", None)
        current = asyncio.current_task()
        if bind is not None and current is not None:
            bind(run.run_id, current)
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
            try:
                pending = getattr(self._runs, "has_pending_interrupt", None)
                should_cancel = task is not None and (
                    task.status is CodingTaskStatus.CANCELLED
                )
                if not should_cancel and pending is not None:
                    should_cancel = bool(await pending(task_id))
                if should_cancel:
                    await self._cancel_active_run(lease, self._clock())
            finally:
                await self._release_lease(lease)
            raise
        except Exception:
            if self._metrics is not None and lease.recovered:
                self._metrics.coding_resume_total.labels(
                    outcome="recovery_required"
                ).inc()
            await self._release_lease(lease)
            raise
        finally:
            if unbind is not None:
                unbind(run.run_id)
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
                    return request
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
            interrupted = await self._apply_interrupt_now_at_safe_point(
                task_id=task_id,
                lease=lease,
                checkpoint=checkpoint,
                worker_id=worker_id or lease.worker_id,
                now=now,
            )
            if interrupted is not None:
                return interrupted
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
        if request is None:
            return False
        if request.mode is SteeringMode.INTERRUPT_NOW:
            run = await self._runs.latest_run(task_id)
            if run is not None:
                await self._runs.update_run(
                    replace(
                        run,
                        status=CodingRunStatus.CANCELLED,
                        completed_at=self._clock(),
                    )
                )
            applied = replace(request, applied_checkpoint_id=checkpoint_id)
            await self._runs.apply_steering(applied)
            await self._append(
                task_id=task_id,
                event_type="steer.applied",
                payload={
                    "steering_id": request.steering_id,
                    "mode": request.mode.value,
                    "instruction": request.instruction,
                },
                checkpoint_id=checkpoint_id,
            )
            return True
        if request.mode is not SteeringMode.SAFE_POINT:
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

    async def stop(self, *, task_id: str, owner_id: str) -> None:
        task = await self._tasks.get_owned(task_id, owner_id)
        if task is None:
            raise CodingTaskNotFound(task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            return
        now = self._clock()
        request = SteeringRequest(
            steering_id=f"cs_{uuid4().hex}",
            task_id=task_id,
            mode=SteeringMode.CANCEL,
            instruction="stop",
            requested_at=now,
        )
        await self._runs.queue_steering(request)
        await self._append(
            task_id=task_id,
            event_type="steer.queued",
            payload={"steering_id": request.steering_id, "mode": request.mode.value},
        )
        await self._mark_task_cancelled(task_id, now)
        run = await self._runs.latest_run(task_id)
        if run is None or run.status is not CodingRunStatus.RUNNING:
            await self._apply_queued_cancel(request)
            return
        lease = await self._runs.acquire_execution_lease(
            task_id=task_id,
            run_id=run.run_id,
            worker_id=f"stop:{request.steering_id}",
            now=now,
            expires_at=now + self._execution_lease,
        )
        if lease is None:
            return
        try:
            await self._cancel_active_run(lease, now)
            await self._apply_queued_cancel(request)
        finally:
            await self._release_lease(lease)

    async def _mark_task_cancelled(self, task_id: str, now: datetime) -> None:
        marker = getattr(self._runs, "mark_task_cancelled", None)
        if marker is not None:
            await marker(task_id=task_id, now=now)
        saver = getattr(self._tasks, "save", None)
        task = await self._tasks.get(task_id)
        if saver is None or task is None:
            return
        if task.status in TERMINAL_TASK_STATUSES:
            return
        await saver(replace(task, status=CodingTaskStatus.CANCELLED, updated_at=now))

    async def _cancel_active_run(self, lease, now: datetime):
        await self._cancel_parent_children(lease, now)
        cancel = getattr(self._runs, "cancel_run", None)
        if cancel is not None:
            return await cancel(lease=lease, now=now)
        run = await self._runs.latest_run(lease.task_id)
        if run is None:
            return None
        await self._runs.update_run(
            replace(run, status=CodingRunStatus.CANCELLED, completed_at=now)
        )
        return None

    async def _cancel_parent_children(self, lease, now: datetime) -> None:
        cancel = getattr(self._loop, "cancel_active_child_for_task", None)
        if cancel is not None:
            await cancel(lease.task_id)
        await self._fail_open_delegated_spawn(lease, now)

    async def _fail_open_delegated_spawn(self, lease, now: datetime) -> None:
        latest = getattr(self._runs, "latest_checkpoint", None)
        if not callable(latest):
            return
        try:
            checkpoint = await latest(lease.task_id)
        except Exception:
            return
        if checkpoint is None:
            return
        loop_state = checkpoint.loop_state or {}
        discard = getattr(self._loop, "discard_child_worktrees", None)
        if callable(discard):
            discard(loop_state)
        tool_call_ids: list[str] = []
        raw_children = loop_state.get("active_children")
        if isinstance(raw_children, list):
            for item in raw_children:
                if not isinstance(item, dict):
                    continue
                tool_call_id = item.get("tool_call_id")
                if tool_call_id:
                    tool_call_ids.append(str(tool_call_id))
        if not tool_call_ids:
            scalar = loop_state.get("active_child_tool_call_id")
            if scalar:
                tool_call_ids.append(str(scalar))
        for tool_call_id in tool_call_ids:
            try:
                claim = await self._runs.claim_tool_execution(
                    lease=lease,
                    tool_call_id=tool_call_id,
                    now=now,
                    claim_expires_at=now
                    + timedelta(seconds=self._child_lease_horizon()),
                )
            except Exception:
                continue
            if claim.disposition not in {
                ToolExecutionDisposition.CLAIMED,
                ToolExecutionDisposition.RECLAIMED,
                ToolExecutionDisposition.DELEGATED,
            }:
                continue
            try:
                await self._runs.complete_tool_execution(
                    claim,
                    result={"status": "error", "reason_code": "aborted"},
                    now=now,
                )
            except Exception:
                continue

    def _child_lease_horizon(self) -> float:
        timeout = 120.0
        config = getattr(self._loop, "_config", None)
        if config is not None:
            timeout = float(getattr(config, "timeout_sec", 120.0) or 120.0)
        return max(self._execution_lease.total_seconds(), timeout + 30.0)

    async def _renew_lease_for_child(self, lease, checkpoint, now: datetime):
        loop_state = getattr(checkpoint, "loop_state", None) if checkpoint else None
        if not isinstance(loop_state, dict) or not (
            loop_state.get("active_children") or loop_state.get("active_child_run_id")
        ):
            return lease
        renew = getattr(self._runs, "renew_execution_lease", None)
        if not callable(renew):
            return lease
        return await renew(
            lease,
            now=now,
            expires_at=now + timedelta(seconds=self._child_lease_horizon()),
        )

    async def _apply_queued_cancel(self, request: SteeringRequest) -> None:
        claim = getattr(self._runs, "claim_pending_interrupt", None)
        claimed = request
        if claim is not None:
            found = await claim(request.task_id)
            if found is not None:
                claimed = found
        await self._runs.apply_steering(claimed)

    async def _apply_interrupt_now_at_safe_point(
        self,
        *,
        task_id: str,
        lease,
        checkpoint: CodingCheckpoint,
        worker_id: str,
        now: datetime,
    ) -> SteeringApplication | None:
        claim = getattr(self._runs, "claim_pending_interrupt", None)
        if claim is not None:
            request = await claim(task_id)
        else:
            checker = getattr(self._runs, "has_pending_interrupt", None)
            if checker is None or not await checker(task_id):
                return None
            request = await self._runs.claim_pending_steering(task_id)
            if request is None or request.mode is not SteeringMode.INTERRUPT_NOW:
                return None
        if request is None:
            return None
        if request.mode is SteeringMode.INTERRUPT_NOW:
            await self._cancel_parent_children(lease, now)
        if request.mode is SteeringMode.CANCEL:
            committed = await self._cancel_active_run(lease, now)
            await self._mark_task_cancelled(task_id, now)
            run = await self._runs.latest_run(task_id)
            applied = replace(request, applied_checkpoint_id=checkpoint.checkpoint_id)
            await self._runs.apply_steering(applied)
            event = (
                committed.event
                if committed is not None
                else await self._append(
                    task_id=task_id,
                    event_type="run.cancelled",
                    payload={"status": "cancelled"},
                    checkpoint_id=checkpoint.checkpoint_id,
                )
            )
            cancelled = run or replace(
                CodingRun(
                    run_id=lease.run_id,
                    task_id=task_id,
                    attempt=1,
                    status=CodingRunStatus.CANCELLED,
                    resume_from_checkpoint_id=None,
                    started_at=now,
                    completed_at=now,
                )
            )
            return SteeringApplication(
                request=applied,
                checkpoint=checkpoint,
                previous_run=cancelled,
                run=cancelled,
                lease=lease,
                event=event,
            )
        run = await self._runs.latest_run(task_id)
        if run is None:
            applied = replace(request, applied_checkpoint_id=checkpoint.checkpoint_id)
            await self._runs.apply_steering(applied)
            return None
        cancelled = replace(
            run,
            status=CodingRunStatus.CANCELLED,
            completed_at=now,
        )
        await self._runs.update_run(cancelled)
        applied = replace(request, applied_checkpoint_id=checkpoint.checkpoint_id)
        await self._runs.apply_steering(applied)
        event = await self._append(
            task_id=task_id,
            event_type="steer.applied",
            payload={
                "steering_id": request.steering_id,
                "mode": request.mode.value,
                "instruction": request.instruction,
            },
            checkpoint_id=checkpoint.checkpoint_id,
        )
        if self._metrics is not None:
            latency = max(0.0, (now - request.requested_at).total_seconds())
            self._metrics.coding_steering_latency_seconds.labels(
                outcome="applied"
            ).observe(latency)
        return SteeringApplication(
            request=applied,
            checkpoint=checkpoint,
            previous_run=cancelled,
            run=cancelled,
            lease=lease,
            event=event,
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
