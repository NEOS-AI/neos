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
from neos.coding.loop.anthropic import CodingLoopFailure, CodingLoopWaitingApproval


_EXPECTED_CHECKPOINT_OMITTED = object()


class CodingTaskOutcome(StrEnum):
    COMPLETED = "completed"
    CONTINUING = "continuing"
    WAITING_APPROVAL = "waiting_approval"
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
        advance_until_complete: bool = False,
        on_lifecycle: Callable[[str, str, dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> None:
        self._runs = runs
        self._policy = policy or CodingTaskExecutionPolicy()
        self._sleep = sleep
        self._on_retry = on_retry
        self._propagate_exceptions = propagate_exceptions
        self._advance_until_complete = advance_until_complete
        self._on_lifecycle = on_lifecycle

    async def run(
        self,
        *,
        task_id: str,
        worker_id: str,
        failure_error_code: str,
        expected_checkpoint_id: str | None | object = _EXPECTED_CHECKPOINT_OMITTED,
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
                advance_kwargs = {
                    "task_id": task_id,
                    "worker_id": worker_id,
                }
                if expected_checkpoint_id is not _EXPECTED_CHECKPOINT_OMITTED:
                    advance_kwargs["expected_checkpoint_id"] = expected_checkpoint_id
                event = await self._runs.advance_one_safe_point(**advance_kwargs)
            except RunAlreadyLeased:
                return CodingTaskOutcome.LEASE_BUSY
            except StaleExecutionLease:
                return CodingTaskOutcome.STALE
            except CodingLoopWaitingApproval:
                return CodingTaskOutcome.WAITING_APPROVAL
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
                await self._emit_lifecycle(task_id, "completed", event)
                return CodingTaskOutcome.COMPLETED
            if event.type == "run.cancelled":
                await self._emit_lifecycle(task_id, "cancelled", event)
                return CodingTaskOutcome.FAILED
            if event.type == "approval.requested":
                await self._emit_lifecycle(task_id, "waiting_approval", event)
                return CodingTaskOutcome.WAITING_APPROVAL
            if not self._advance_until_complete:
                return CodingTaskOutcome.CONTINUING
        raise asyncio.CancelledError

    async def _emit_lifecycle(self, task_id: str, status: str, event: Any) -> None:
        if self._on_lifecycle is None:
            return
        payload = dict(getattr(event, "payload", None) or {})
        try:
            await self._on_lifecycle(task_id, status, payload)
        except Exception:
            return
