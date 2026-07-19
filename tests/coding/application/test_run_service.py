from datetime import UTC, datetime, timedelta

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


async def make_run_service(repository) -> CodingRunService:
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
    return CodingRunService(
        tasks=tasks,
        runs=repository,
        events=InMemoryCodingEventStore(),
        interrupter=RecordingInterrupter(repository),
        clock=lambda: NOW,
    )


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
    assert applied.checkpoint.loop_state["transcript"] == checkpoint.loop_state[
        "transcript"
    ]
    assert applied.run.attempt == 2
    assert applied.lease.fencing_token == lease.fencing_token + 1
