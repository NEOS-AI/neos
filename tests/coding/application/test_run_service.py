from datetime import UTC, datetime

from neos.coding.application.run_service import (
    CodingRunService,
    InterruptionResult,
)
from neos.coding.application.task_service import InMemoryCodingTaskRepository
from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.domain.phases import CodingRun, CodingRunStatus, SteeringMode
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
