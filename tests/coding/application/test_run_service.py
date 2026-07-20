from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.application.run_service import (
    CodingRunService,
    InterruptionResult,
)
from neos.coding.application.task_service import InMemoryCodingTaskRepository
from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class RecordingInterrupter:
    def __init__(self, repository) -> None:
        self.repository = repository

    async def interrupt(self, run_id: str) -> InterruptionResult:
        self.repository.interrupt_calls.append(run_id)
        return InterruptionResult("workspace:interrupted", True)


def run_fixture(run_id: str) -> CodingRun:
    return CodingRun(
        run_id=run_id,
        task_id="ct_1",
        attempt=1,
        status=CodingRunStatus.RUNNING,
        resume_from_checkpoint_id=None,
        started_at=NOW,
    )


async def make_run_service(
    repository, *, loop=None, execution_lease=None
) -> CodingRunService:
    tasks = InMemoryCodingTaskRepository()
    await tasks.create(
        CodingTask(
            task_id="ct_1",
            owner_id="u1",
            prompt="Fix it",
            status=CodingTaskStatus.QUEUED,
            version=1,
            last_seq=0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    kwargs = {}
    if execution_lease is not None:
        kwargs["execution_lease"] = execution_lease
    return CodingRunService(
        tasks=tasks,
        runs=repository,
        events=InMemoryCodingEventStore(),
        interrupter=RecordingInterrupter(repository),
        loop=loop,
        clock=lambda: NOW,
        **kwargs,
    )


class FailingLoop:
    async def run(self, input, checkpoint, deps):
        if False:
            yield None
        raise RuntimeError("transient")


class ModelCheckpointLoop:
    def __init__(self, *, deny_first=False) -> None:
        self.calls = 0
        self.deny_first = deny_first

    async def run(self, input, checkpoint, deps):
        self.calls += 1
        if checkpoint is not None and checkpoint.loop_state.get("terminal_pending"):
            return
        denied = self.deny_first and self.calls == 1
        committed = await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type="tool.denied" if denied else "model.completed",
            event_payload={"reason_code": "policy_unknown_tool"}
            if denied
            else {"stop_reason": "end_turn"},
            loop_state={
                "current_instruction": input.instruction,
                "terminal_pending": not denied,
            },
            workspace_revision="rev_1",
            now=NOW,
        )
        yield committed.event


class RecordingLeaseRepository(InMemoryCodingRunRepository):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.requested_expirations = []

    async def acquire_execution_lease(self, **kwargs):
        self.requested_expirations.append(kwargs["expires_at"])
        return await super().acquire_execution_lease(**kwargs)


async def test_safe_point_steering_is_applied_after_checkpoint() -> None:
    repository = InMemoryCodingRunRepository()
    service = await make_run_service(repository)

    steering = await service.steer(
        task_id="ct_1",
        owner_id="u1",
        instruction="Also update docs",
        mode=SteeringMode.SAFE_POINT,
    )
    await service.on_safe_point(task_id="ct_1", checkpoint_id="cc_5")

    assert steering.mode is SteeringMode.SAFE_POINT
    assert repository.applied_steering[0].applied_checkpoint_id == "cc_5"
    assert repository.interrupt_calls == []


async def test_interrupt_steering_creates_new_run_from_checkpoint() -> None:
    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"))
    service = await make_run_service(repository)

    await service.steer(
        task_id="ct_1",
        owner_id="u1",
        instruction="Stop editing auth and inspect cache",
        mode=SteeringMode.INTERRUPT_NOW,
    )

    assert repository.interrupt_calls == ["cr_1"]
    assert repository.created_runs[-1].resume_from_checkpoint_id.startswith(
        "cc_interrupt_"
    )
    assert repository.created_runs[-1].attempt == 2
    assert repository.active_run.status is CodingRunStatus.RUNNING


async def test_safe_point_steering_uses_atomic_repository_transition() -> None:
    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"))
    service = await make_run_service(repository)
    checkpoint = CodingCheckpoint(
        checkpoint_id="cc_5",
        task_id="ct_1",
        run_id="cr_1",
        seq=5,
        loop_state={
            "phase_index": 1,
            "transcript": [{"role": "assistant", "content": "planned"}],
            "current_instruction": "Fix it",
            "pending_instruction": None,
        },
        workspace_revision="rev_5",
        created_at=NOW,
    )
    await repository.save_checkpoint(checkpoint)
    lease = await repository.acquire_execution_lease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id="worker-a",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert lease is not None
    steering = await service.steer(
        task_id="ct_1",
        owner_id="u1",
        instruction="Inspect cache first",
        mode=SteeringMode.SAFE_POINT,
    )
    repository.steering_claims[steering.steering_id] = (
        "dead-worker",
        NOW - timedelta(seconds=1),
    )

    applied = await service.on_safe_point(
        task_id="ct_1",
        checkpoint_id=checkpoint.checkpoint_id,
        lease=lease,
        checkpoint=checkpoint,
        worker_id="worker-a",
    )

    assert applied is not False
    assert applied.checkpoint.loop_state["current_instruction"] == (
        "Inspect cache first"
    )
    assert (
        applied.checkpoint.loop_state["transcript"]
        == checkpoint.loop_state["transcript"]
    )
    assert applied.run.attempt == 2
    assert applied.lease.fencing_token == lease.fencing_token + 1


async def test_ensure_started_is_idempotent_and_uses_task_prompt() -> None:
    repository = InMemoryCodingRunRepository(task_prompts={"ct_1": "Fix it"})
    service = await make_run_service(repository)

    first = await service.ensure_started(task_id="ct_1")
    second = await service.ensure_started(task_id="ct_1")

    assert first == second
    assert first.status is CodingRunStatus.RUNNING
    assert repository.task_statuses["ct_1"] == "running"


async def test_caught_exception_releases_lease_for_retry() -> None:
    repository = InMemoryCodingRunRepository(
        active_run=run_fixture("cr_1"),
        task_prompts={"ct_1": "Fix it"},
    )
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(repository, loop=FailingLoop())

    with pytest.raises(RuntimeError, match="transient"):
        await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")

    assert repository.execution_leases["ct_1"].expires_at == NOW


async def test_no_remaining_phase_completes_run_and_task_atomically() -> None:
    repository = InMemoryCodingRunRepository(
        active_run=run_fixture("cr_1"),
        task_prompts={"ct_1": "Fix it"},
    )
    repository.task_statuses["ct_1"] = "running"
    await repository.save_checkpoint(
        CodingCheckpoint(
            checkpoint_id="cc_final",
            task_id="ct_1",
            run_id="cr_1",
            seq=10,
            loop_state={
                "phase_index": 4,
                "transcript": [],
                "current_instruction": "Fix it",
                "pending_instruction": None,
            },
            workspace_revision="rev_final",
            created_at=NOW,
        )
    )
    service = await make_run_service(
        repository,
        loop=FakeDurableCodingLoop(clock=lambda: NOW),
    )

    event = await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")

    assert event.type == "run.completed"
    assert repository.active_run.status is CodingRunStatus.COMPLETED
    assert repository.task_statuses["ct_1"] == "completed"


async def test_model_checkpoint_is_one_safe_point_before_run_completion() -> None:
    repository = InMemoryCodingRunRepository(
        active_run=run_fixture("cr_1"), task_prompts={"ct_1": "Fix it"}
    )
    repository.task_statuses["ct_1"] = "running"
    loop = ModelCheckpointLoop()
    service = await make_run_service(repository, loop=loop)

    first = await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")
    assert first.type == "model.completed"
    assert repository.active_run.status is CodingRunStatus.RUNNING

    second = await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")
    assert second.type == "run.completed"
    assert repository.active_run.status is CodingRunStatus.COMPLETED


async def test_denial_checkpoint_returns_then_continues_model_on_next_call() -> None:
    repository = InMemoryCodingRunRepository(
        active_run=run_fixture("cr_1"), task_prompts={"ct_1": "Fix it"}
    )
    repository.task_statuses["ct_1"] = "running"
    loop = ModelCheckpointLoop(deny_first=True)
    service = await make_run_service(repository, loop=loop)

    denied = await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")
    assert denied.type == "tool.denied"
    assert repository.active_run.status is CodingRunStatus.RUNNING

    completed = await service.advance_one_safe_point(
        task_id="ct_1", worker_id="worker-a"
    )
    assert completed.type == "model.completed"
    assert loop.calls == 2


async def test_fail_active_run_uses_fenced_terminal_command() -> None:
    repository = InMemoryCodingRunRepository(
        active_run=run_fixture("cr_1"),
        task_prompts={"ct_1": "Fix it"},
    )
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(repository)

    event = await service.fail_active_run(
        task_id="ct_1",
        worker_id="worker-a",
        error_code="supervisor_retry_exhausted",
    )

    assert event.type == "run.failed"
    assert repository.active_run.status is CodingRunStatus.FAILED
    assert repository.task_statuses["ct_1"] == "failed"


async def test_configured_execution_lease_controls_repository_expiry() -> None:
    repository = RecordingLeaseRepository(
        active_run=run_fixture("cr_1"),
        task_prompts={"ct_1": "Fix it"},
    )
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(
        repository,
        loop=FailingLoop(),
        execution_lease=timedelta(seconds=75),
    )

    with pytest.raises(RuntimeError, match="transient"):
        await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")

    assert repository.requested_expirations == [NOW + timedelta(seconds=75)]
