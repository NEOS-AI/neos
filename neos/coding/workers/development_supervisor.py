import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from neos.coding.domain.durability import (
    RunAlreadyLeased,
    StaleExecutionLease,
)


class CodingDevelopmentSupervisor:
    """Runs coding tasks in-process for development environments only."""

    def __init__(
        self,
        *,
        runs: Any,
        work_repository: Any,
        metrics: Any | None = None,
        reconciliation_interval: float = 2.0,
        discovery_batch_size: int = 100,
        retry_backoffs: tuple[float, ...] = (1.0, 2.0, 4.0),
        shutdown_timeout: float = 10.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        worker_id: str | None = None,
    ) -> None:
        if reconciliation_interval <= 0:
            raise ValueError("reconciliation_interval must be positive")
        if discovery_batch_size <= 0:
            raise ValueError("discovery_batch_size must be positive")
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        if any(delay < 0 for delay in retry_backoffs):
            raise ValueError("retry_backoffs cannot contain negative values")

        self.worker_id = worker_id or f"coding-dev-{uuid4().hex}"
        self.outcomes: list[str] = []
        self._runs = runs
        self._work_repository = work_repository
        self._metrics = metrics
        self._reconciliation_interval = reconciliation_interval
        self._discovery_batch_size = discovery_batch_size
        self._retry_backoffs = retry_backoffs
        self._shutdown_timeout = shutdown_timeout
        self._sleep = sleep
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._active: dict[str, asyncio.Task[None]] = {}
        self._loop_tasks: list[asyncio.Task[None]] = []
        self._accepting = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._stop_requested = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._accepting

    async def start(self) -> None:
        if self._accepting:
            return
        self._accepting = True
        self._stop_requested.clear()
        await self._reconcile_once()
        self._loop_tasks = [
            asyncio.create_task(
                self._dispatch_loop(), name="coding-dev-dispatch"
            ),
            asyncio.create_task(
                self._reconciliation_loop(), name="coding-dev-reconcile"
            ),
        ]

    def notify(self, task_id: str) -> bool:
        if (
            not self._accepting
            or task_id in self._queued
            or task_id in self._active
        ):
            return False
        self._queued.add(task_id)
        self._idle.clear()
        self._pending.put_nowait(task_id)
        return True

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def stop(self) -> None:
        self._accepting = False
        self._stop_requested.set()
        for task in self._loop_tasks:
            task.cancel()
        await asyncio.gather(*self._loop_tasks, return_exceptions=True)
        self._loop_tasks.clear()

        runners = list(self._active.values())
        for runner in runners:
            runner.cancel()
        if runners:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*runners, return_exceptions=True),
                    timeout=self._shutdown_timeout,
                )
            except TimeoutError:
                for runner in runners:
                    runner.cancel()

        self._active.clear()
        self._queued.clear()
        while not self._pending.empty():
            try:
                self._pending.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._idle.set()

    async def _dispatch_loop(self) -> None:
        while self._accepting:
            task_id = await self._pending.get()
            self._queued.discard(task_id)
            if task_id in self._active:
                continue
            runner = asyncio.create_task(
                self._run_task(task_id), name=f"coding-dev-run-{task_id}"
            )
            self._active[task_id] = runner
            runner.add_done_callback(
                lambda completed, task_id=task_id: self._runner_done(
                    task_id, completed
                )
            )

    def _runner_done(
        self, task_id: str, completed: asyncio.Task[None]
    ) -> None:
        if self._active.get(task_id) is completed:
            self._active.pop(task_id, None)
        if not completed.cancelled() and completed.exception() is not None:
            self._record_outcome("runner_error")
        if not self._queued and not self._active:
            self._idle.set()

    async def _reconciliation_loop(self) -> None:
        while self._accepting:
            try:
                await asyncio.wait_for(
                    self._stop_requested.wait(),
                    timeout=self._reconciliation_interval,
                )
                return
            except TimeoutError:
                await self._reconcile_once()

    async def _reconcile_once(self) -> None:
        task_ids = await self._work_repository.claimable_task_ids(
            limit=self._discovery_batch_size
        )
        for task_id in task_ids:
            self.notify(task_id)

    async def _run_task(self, task_id: str) -> None:
        await self._runs.ensure_started(task_id=task_id)
        failures = 0
        while self._accepting:
            try:
                event = await self._runs.advance_one_safe_point(
                    task_id=task_id, worker_id=self.worker_id
                )
            except RunAlreadyLeased:
                self._record_outcome("lease_busy")
                return
            except StaleExecutionLease:
                self._record_stale_write()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if failures >= len(self._retry_backoffs):
                    try:
                        await self._runs.fail_active_run(
                            task_id=task_id,
                            worker_id=self.worker_id,
                            error_code="supervisor_retry_exhausted",
                        )
                    except RunAlreadyLeased:
                        self._record_outcome("lease_busy")
                        return
                    self._record_outcome("failed")
                    return
                delay = self._retry_backoffs[failures]
                failures += 1
                self._record_retry("unexpected")
                await self._sleep(delay)
                continue
            failures = 0
            if event is None or event.type == "run.completed":
                self._record_outcome("completed")
                return

    def _record_outcome(self, outcome: str) -> None:
        self.outcomes.append(outcome)
        self._increment_metric("coding_supervisor_outcome_total", outcome=outcome)

    def _record_retry(self, reason: str) -> None:
        self._increment_metric("coding_supervisor_retry_total", reason=reason)

    def _record_stale_write(self) -> None:
        self._increment_metric("coding_stale_write_total", outcome="rejected")

    def _increment_metric(self, name: str, **labels: str) -> None:
        metric = getattr(self._metrics, name, None)
        if metric is not None:
            metric.labels(**labels).inc()
