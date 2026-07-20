import asyncio
from types import SimpleNamespace

import pytest

from neos.coding.domain.durability import (
    RunAlreadyLeased,
    StaleExecutionLease,
)
from neos.coding.loop.anthropic import CodingLoopFailure
from neos.coding.workers.execution import (
    CodingTaskExecutionPolicy,
    CodingTaskOutcome,
    CodingTaskRunner,
)


class RecordingRuns:
    def __init__(self, effects) -> None:
        self.effects = list(effects)
        self.ensure_calls: list[str] = []
        self.advance_calls: list[tuple[str, str]] = []
        self.fail_calls: list[tuple[str, str, str]] = []

    async def ensure_started(self, *, task_id: str) -> None:
        self.ensure_calls.append(task_id)

    async def advance_one_safe_point(self, *, task_id: str, worker_id: str):
        self.advance_calls.append((task_id, worker_id))
        effect = self.effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect

    async def fail_active_run(
        self, *, task_id: str, worker_id: str, error_code: str
    ) -> None:
        self.fail_calls.append((task_id, worker_id, error_code))


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


async def test_runner_returns_completed_for_terminal_event() -> None:
    runs = RecordingRuns([SimpleNamespace(type="run.completed")])
    runner = CodingTaskRunner(runs=runs)

    outcome = await runner.run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )

    assert outcome is CodingTaskOutcome.COMPLETED
    assert runs.ensure_calls == ["ct_1"]


async def test_runner_advances_exactly_one_safe_point_per_delivery() -> None:
    runs = RecordingRuns(
        [SimpleNamespace(type="phase.checkpointed"), SimpleNamespace(type="run.completed")]
    )

    outcome = await CodingTaskRunner(runs=runs).run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )

    assert outcome is CodingTaskOutcome.CONTINUING
    assert runs.advance_calls == [("ct_1", "worker-1")]


async def test_runner_returns_waiting_without_retrying_approval_checkpoint() -> None:
    runs = RecordingRuns([SimpleNamespace(type="approval.requested")])

    outcome = await CodingTaskRunner(runs=runs).run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )

    assert outcome is CodingTaskOutcome.WAITING_APPROVAL
    assert runs.advance_calls == [("ct_1", "worker-1")]
    assert runs.fail_calls == []


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (RunAlreadyLeased("ct_1"), CodingTaskOutcome.LEASE_BUSY),
        (StaleExecutionLease("ct_1"), CodingTaskOutcome.STALE),
    ],
)
async def test_runner_maps_fencing_exits_to_bounded_outcomes(
    effect: BaseException, expected: CodingTaskOutcome
) -> None:
    runner = CodingTaskRunner(runs=RecordingRuns([effect]))

    outcome = await runner.run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )

    assert outcome is expected


async def test_runner_retries_1_2_4_then_fails_atomically() -> None:
    sleeps = RecordingSleeper()
    runs = RecordingRuns([RuntimeError("transient")] * 4)
    runner = CodingTaskRunner(
        runs=runs,
        policy=CodingTaskExecutionPolicy(retry_backoffs=(1.0, 2.0, 4.0)),
        sleep=sleeps,
    )

    outcome = await runner.run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )

    assert outcome is CodingTaskOutcome.FAILED
    assert sleeps.delays == [1.0, 2.0, 4.0]
    assert runs.fail_calls == [("ct_1", "worker-1", "worker_retry_exhausted")]


async def test_runner_propagates_configured_infrastructure_exception() -> None:
    runs = RecordingRuns([ConnectionError("database unavailable")])
    runner = CodingTaskRunner(runs=runs, propagate_exceptions=(ConnectionError,))

    with pytest.raises(ConnectionError, match="database unavailable"):
        await runner.run(
            task_id="ct_1",
            worker_id="worker-1",
            failure_error_code="worker_retry_exhausted",
        )

    assert runs.fail_calls == []


async def test_runner_does_not_retry_nonretryable_coding_failure() -> None:
    sleeps = RecordingSleeper()
    runs = RecordingRuns([CodingLoopFailure("tool_outcome_unknown", retryable=False)])
    runner = CodingTaskRunner(runs=runs, sleep=sleeps)

    outcome = await runner.run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )

    assert outcome is CodingTaskOutcome.FAILED
    assert sleeps.delays == []
    assert len(runs.advance_calls) == 1
    assert runs.fail_calls == [("ct_1", "worker-1", "tool_outcome_unknown")]
