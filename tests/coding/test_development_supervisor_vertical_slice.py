import asyncio
from datetime import UTC, datetime

from neos.coding.application.run_service import InProcessRunInterrupter
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.runtime import create_coding_runtime
from neos.coding.workers.development_supervisor import (
    CodingDevelopmentSupervisor,
)
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


class EmptyProjectionRepository:
    async def snapshot(self, task_id: str):
        return None


class PauseAfterUnderstand:
    def __init__(self, runs) -> None:
        self._runs = runs
        self.understood = asyncio.Event()
        self.release = asyncio.Event()

    async def ensure_started(self, **kwargs):
        return await self._runs.ensure_started(**kwargs)

    async def advance_one_safe_point(self, **kwargs):
        event = await self._runs.advance_one_safe_point(**kwargs)
        if event is not None and event.type == "phase.completed":
            if event.payload.get("phase") == "understand":
                self.understood.set()
                await self.release.wait()
        return event

    async def fail_active_run(self, **kwargs):
        return await self._runs.fail_active_run(**kwargs)


def make_harness(*, pause_after_understand: bool = False):
    task_id = "ct_automatic"
    prompt = "Fix it"
    task_repository = InMemoryCodingTaskRepository()
    events = InMemoryCodingEventStore()
    tasks = CodingTaskService(task_repository, events, clock=lambda: NOW)
    work_repository = InMemoryCodingRunRepository(
        task_prompts={task_id: prompt}
    )
    runtime = create_coding_runtime(
        events=events,
        tasks=task_repository,
        run_repository=work_repository,
        projection_repository=EmptyProjectionRepository(),
        loop=FakeDurableCodingLoop(clock=lambda: NOW),
        interrupter=InProcessRunInterrupter(),
        clock=lambda: NOW,
    )
    runs = (
        PauseAfterUnderstand(runtime.runs)
        if pause_after_understand
        else runtime.runs
    )
    supervisor = CodingDevelopmentSupervisor(
        runs=runs,
        work_repository=work_repository,
        reconciliation_interval=60.0,
        worker_id="worker-first",
    )
    tasks.set_task_created_notifier(supervisor.notify)
    return tasks, work_repository, runtime.runs, supervisor, runs


async def test_created_task_runs_automatically_without_manual_driver() -> None:
    tasks, repository, _, supervisor, _ = make_harness()
    await supervisor.start()

    task = await tasks.create_task(
        owner_id="u1",
        prompt="Fix it",
        task_id="ct_automatic",
    )
    await supervisor.wait_idle()

    assert repository.active_run.task_id == task.task_id
    assert repository.checkpoints[0].loop_state["current_instruction"] == "Fix it"
    assert repository.task_statuses[task.task_id] == "completed"
    await supervisor.stop()


async def test_replacement_supervisor_rediscovers_unfinished_task() -> None:
    tasks, repository, base_runs, first, pausing_runs = make_harness(
        pause_after_understand=True
    )
    await first.start()
    await tasks.create_task(
        owner_id="u1",
        prompt="Fix it",
        task_id="ct_automatic",
    )
    await pausing_runs.understood.wait()
    await first.stop()

    replacement = CodingDevelopmentSupervisor(
        runs=base_runs,
        work_repository=repository,
        reconciliation_interval=60.0,
        worker_id="worker-replacement",
    )
    await replacement.start()
    await replacement.wait_idle()

    completed = [
        (phase.kind.value, phase.attempt)
        for phase in repository.phases
        if phase.status.value == "completed"
    ]
    assert completed.count(("understand", 1)) == 1
    assert completed.count(("plan", 1)) == 1
    await replacement.stop()
