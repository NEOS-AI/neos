import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from neos.coding.domain.durability import (
    RunAlreadyLeased,
    StaleExecutionLease,
)
from neos.coding.domain.phases import CodingRunStatus
from neos.coding.loop.anthropic import CodingLoopFailure


class CodingTaskOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    LEASE_BUSY = "lease_busy"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class CodingTaskExecutionPolicy:
    retry_backoffs: tuple[float, ...] = (1.0, 2.0, 4.0)

    def __post_init__(self) -> None:
        if any(delay < 0 for delay in self.retry_backoffs):
            raise ValueError("retry_backoffs cannot contain negative values")


class CodingTaskRunner:
    def __init__(
        self,
        *,
        runs: Any,
        policy: CodingTaskExecutionPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_retry: Callable[[str], None] | None = None,
        propagate_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        self._runs = runs
        self._policy = policy or CodingTaskExecutionPolicy()
        self._sleep = sleep
        self._on_retry = on_retry
        self._propagate_exceptions = propagate_exceptions

    async def run(
        self,
        *,
        task_id: str,
        worker_id: str,
        failure_error_code: str,
        keep_running: Callable[[], bool] = lambda: True,
    ) -> CodingTaskOutcome:
        run = await self._runs.ensure_started(task_id=task_id)
        if run is not None and run.status is CodingRunStatus.COMPLETED:
            return CodingTaskOutcome.COMPLETED
        if run is not None and run.status in {
            CodingRunStatus.FAILED,
            CodingRunStatus.CANCELLED,
        }:
            return CodingTaskOutcome.FAILED
        failures = 0
        while keep_running():
            try:
                event = await self._runs.advance_one_safe_point(
                    task_id=task_id, worker_id=worker_id
                )
            except RunAlreadyLeased:
                return CodingTaskOutcome.LEASE_BUSY
            except StaleExecutionLease:
                return CodingTaskOutcome.STALE
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                if isinstance(exc, self._propagate_exceptions):
                    raise
                if not isinstance(exc, Exception):
                    raise
                if isinstance(exc, CodingLoopFailure) and not exc.retryable:
                    try:
                        await self._runs.fail_active_run(
                            task_id=task_id,
                            worker_id=worker_id,
                            error_code=exc.code,
                        )
                    except RunAlreadyLeased:
                        return CodingTaskOutcome.LEASE_BUSY
                    return CodingTaskOutcome.FAILED
                if failures >= len(self._policy.retry_backoffs):
                    try:
                        await self._runs.fail_active_run(
                            task_id=task_id,
                            worker_id=worker_id,
                            error_code=failure_error_code,
                        )
                    except RunAlreadyLeased:
                        return CodingTaskOutcome.LEASE_BUSY
                    return CodingTaskOutcome.FAILED
                delay = self._policy.retry_backoffs[failures]
                failures += 1
                if self._on_retry is not None:
                    self._on_retry("unexpected")
                await self._sleep(delay)
                continue
            failures = 0
            if event is None or event.type == "run.completed":
                return CodingTaskOutcome.COMPLETED
        raise asyncio.CancelledError
