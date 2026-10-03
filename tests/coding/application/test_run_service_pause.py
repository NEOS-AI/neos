"""Q10b around the loop: a paused task is not "completed", does not move, and only
its owner resumes it.

In Postgres the task row is one row; the in-memory fakes keep the run
repository's `task_statuses` and the task repository apart, so these tests set
the one each path reads.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.domain.durability import TaskPaused, is_pause_event
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.models import CodingTaskStatus
from neos.coding.domain.phases import CodingRunStatus
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner
from tests.coding.application.test_run_service import NOW, make_run_service, run_fixture
from tests.coding.fakes import InMemoryCodingRunRepository

pytestmark = pytest.mark.no_db


class PausingLoop:
    """What the durable loop does over an enforcing envelope: commit the pause, hand it back."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, input, checkpoint, deps):
        self.calls += 1
        commit = await deps.repository.pause_task(
            lease=deps.lease,
            judgement_type="budget.judged",
            judgement={"would_pause": True, "enforced": True},
            reason_code="budget_envelope_exhausted",
            now=NOW,
        )
        yield commit.status_event


def _repository():
    repository = InMemoryCodingRunRepository(task_prompts={"ct_1": "Fix it"})
    run = run_fixture("cr_1")
    repository.active_run = run
    repository.created_runs = [run]
    repository.task_statuses["ct_1"] = "running"
    return repository


@pytest.mark.asyncio
async def test_a_pause_is_handed_back_not_read_as_completion() -> None:
    repository = _repository()
    service = await make_run_service(repository, loop=PausingLoop())

    event = await service.advance_one_safe_point(task_id="ct_1", worker_id="w1")

    assert is_pause_event(event)
    assert repository.active_run.status is CodingRunStatus.RUNNING  # not completed
    assert repository.task_statuses["ct_1"] == "paused"
    assert repository.execution_leases["ct_1"].expires_at <= NOW  # released


@pytest.mark.asyncio
async def test_the_runner_reports_paused_and_tells_the_lifecycle() -> None:
    repository = _repository()
    service = await make_run_service(repository, loop=PausingLoop())
    seen = []

    async def lifecycle(task_id, status, payload):
        seen.append((task_id, status, payload.get("reason_code")))

    runner = CodingTaskRunner(runs=service, advance_until_complete=True, on_lifecycle=lifecycle)
    outcome = await runner.run(task_id="ct_1", worker_id="w1", failure_error_code="x")

    assert outcome is CodingTaskOutcome.PAUSED
    assert seen == [("ct_1", "paused", "budget_envelope_exhausted")]


@pytest.mark.asyncio
async def test_a_paused_task_does_not_move_even_with_a_lease() -> None:
    """The run is still `running`, so a lease can be had -- the task must still not move."""
    repository = _repository()
    loop = PausingLoop()
    service = await make_run_service(repository, loop=loop)
    task = await service._tasks.get("ct_1")
    await service._tasks.save(replace(task, status=CodingTaskStatus.PAUSED))

    with pytest.raises(TaskPaused):
        await service.advance_one_safe_point(task_id="ct_1", worker_id="w1")

    assert loop.calls == 0
    assert repository.execution_leases["ct_1"].expires_at <= NOW  # released
    runner = CodingTaskRunner(runs=service, advance_until_complete=True)
    assert (
        await runner.run(task_id="ct_1", worker_id="w2", failure_error_code="x")
        is CodingTaskOutcome.PAUSED
    )


@pytest.mark.asyncio
async def test_the_owner_resumes_and_a_worker_is_woken() -> None:
    repository = _repository()
    repository.task_statuses["ct_1"] = "paused"
    repository.task_owners["ct_1"] = "u1"
    service = await make_run_service(repository)
    woken = []

    async def wake(task_id, checkpoint_id):
        woken.append((task_id, checkpoint_id))

    service.set_wake(wake)
    commit = await service.resume(task_id="ct_1", owner_id="u1")

    assert commit is not None
    assert commit.event.type == "task.status.changed"
    assert commit.event.payload == {"status": "running", "resumed_by": "owner"}
    assert repository.task_statuses["ct_1"] == "running"
    assert woken == [("ct_1", None)]


@pytest.mark.asyncio
async def test_a_task_that_is_not_paused_is_not_resumed() -> None:
    repository = _repository()
    repository.task_owners["ct_1"] = "u1"
    service = await make_run_service(repository)
    woken = []

    async def wake(task_id, checkpoint_id):
        woken.append(task_id)

    service.set_wake(wake)

    assert await service.resume(task_id="ct_1", owner_id="u1") is None
    assert woken == []
    assert repository.task_statuses["ct_1"] == "running"


@pytest.mark.asyncio
async def test_someone_else_cannot_resume_it() -> None:
    repository = _repository()
    repository.task_statuses["ct_1"] = "paused"
    repository.task_owners["ct_1"] = "u1"
    service = await make_run_service(repository)

    with pytest.raises(CodingTaskNotFound):
        await service.resume(task_id="ct_1", owner_id="intruder")
    assert repository.task_statuses["ct_1"] == "paused"


@pytest.mark.asyncio
async def test_a_failed_wake_still_resumes() -> None:
    """The task is `running` again; the reconciliation sweep finds it."""
    repository = _repository()
    repository.task_statuses["ct_1"] = "paused"
    service = await make_run_service(repository)

    async def wake(task_id, checkpoint_id):
        raise RuntimeError("broker down")

    service.set_wake(wake)

    assert await service.resume(task_id="ct_1", owner_id="u1") is not None
    assert repository.task_statuses["ct_1"] == "running"


@pytest.mark.asyncio
async def test_a_paused_task_can_still_be_cancelled() -> None:
    """Pausing is not a trap: Cancel works on a paused task and closes its run."""
    repository = _repository()
    service = await make_run_service(repository, loop=PausingLoop())
    await service.advance_one_safe_point(task_id="ct_1", worker_id="w1")
    task = await service._tasks.get("ct_1")
    await service._tasks.save(replace(task, status=CodingTaskStatus.PAUSED))

    await service.stop(task_id="ct_1", owner_id="u1")

    assert repository.active_run.status is CodingRunStatus.CANCELLED
    assert repository.task_statuses["ct_1"] == "cancelled"
