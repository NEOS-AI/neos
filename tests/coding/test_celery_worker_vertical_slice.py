import asyncio
from datetime import UTC, datetime, timedelta

from neos.coding.application.run_service import InProcessRunInterrupter
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.runtime import create_coding_runtime
from neos.coding.workers.dispatcher import CodingDispatchSource
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 15, 0, tzinfo=UTC)


class EmptyProjectionRepository:
    async def snapshot(self, task_id: str):
        return None


class EagerRecordingDispatcher:
    def __init__(self) -> None:
        self.deliveries: list[tuple[str, str | None]] = []

    def enqueue(
        self,
        task_id: str,
        *,
        expected_checkpoint_id: str | None,
        source: CodingDispatchSource,
    ) -> str:
        assert source in {CodingDispatchSource.API, CodingDispatchSource.CONTINUATION}
        self.deliveries.append((task_id, expected_checkpoint_id))
        return f"delivery-{len(self.deliveries)}"


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


class CeleryWorkerHarness:
    def __init__(self, *, task_id: str, prompt: str) -> None:
        self.task_id = task_id
        self.prompt = prompt
        self.now = NOW
        self.task_repository = InMemoryCodingTaskRepository()
        self.events = InMemoryCodingEventStore()
        self.tasks = CodingTaskService(
            self.task_repository, self.events, clock=lambda: self.now
        )
        self.repository = InMemoryCodingRunRepository(task_prompts={task_id: prompt})
        self.runtime = create_coding_runtime(
            events=self.events,
            tasks=self.task_repository,
            run_repository=self.repository,
            projection_repository=EmptyProjectionRepository(),
            loop=FakeDurableCodingLoop(clock=lambda: self.now),
            interrupter=InProcessRunInterrupter(),
            clock=lambda: self.now,
        )
        self.dispatcher = EagerRecordingDispatcher()
        self.tasks.set_task_created_notifier(
            lambda task_id: self.dispatcher.enqueue(
                task_id,
                expected_checkpoint_id=None,
                source=CodingDispatchSource.API,
            )
        )

    async def create_task(self):
        return await self.tasks.create_task(
            owner_id="u1", prompt=self.prompt, task_id=self.task_id
        )

    def duplicate_last_delivery(self) -> None:
        self.dispatcher.deliveries.append(self.dispatcher.deliveries[-1])

    async def drain_deliveries(self) -> list[CodingTaskOutcome]:
        outcomes = []
        for index, delivery in enumerate(self.dispatcher.deliveries, start=1):
            task_id, expected_checkpoint_id = delivery
            outcome = await CodingTaskRunner(runs=self.runtime.runs).run(
                task_id=task_id,
                worker_id=f"celery-{index}",
                failure_error_code="worker_retry_exhausted",
                expected_checkpoint_id=expected_checkpoint_id,
            )
            outcomes.append(outcome)
            if outcome is CodingTaskOutcome.CONTINUING:
                self.dispatcher.enqueue(
                    task_id,
                    expected_checkpoint_id=(
                        self.repository.checkpoints[-1].checkpoint_id
                    ),
                    source=CodingDispatchSource.CONTINUATION,
                )
        return outcomes

    def completed_tool_count(self, tool_call_id: str) -> int:
        return sum(
            call["tool_call_id"] == tool_call_id
            for call in self.repository.tool_execution_calls
        )


async def test_post_commit_delivery_runs_fake_loop_to_completion() -> None:
    harness = CeleryWorkerHarness(task_id="ct_eager", prompt="Fix it")

    task = await harness.create_task()
    outcomes = await harness.drain_deliveries()

    assert outcomes[-1] is CodingTaskOutcome.COMPLETED
    assert all(item is CodingTaskOutcome.CONTINUING for item in outcomes[:-1])
    assert harness.repository.active_run.task_id == task.task_id
    assert harness.repository.task_statuses[task.task_id] == "completed"
    assert (
        harness.repository.checkpoints[0].loop_state["current_instruction"] == "Fix it"
    )


async def test_redelivered_initial_generation_cannot_advance_twice() -> None:
    harness = CeleryWorkerHarness(task_id="ct_duplicate", prompt="Fix it")
    await harness.create_task()
    harness.duplicate_last_delivery()

    outcomes = await harness.drain_deliveries()

    assert outcomes[0] is CodingTaskOutcome.CONTINUING
    assert outcomes[1] is CodingTaskOutcome.LEASE_BUSY
    assert outcomes[-1] is CodingTaskOutcome.COMPLETED
    assert len(harness.repository.created_runs) == 1
    assert harness.completed_tool_count("fake_understand_0") == 1


async def test_replacement_delivery_resumes_after_committed_checkpoint() -> None:
    harness = CeleryWorkerHarness(task_id="ct_resume", prompt="Fix it")
    await harness.create_task()
    pausing_runs = PauseAfterUnderstand(harness.runtime.runs)
    first = asyncio.create_task(
        CodingTaskRunner(runs=pausing_runs).run(
            task_id=harness.task_id,
            worker_id="celery-first",
            failure_error_code="worker_retry_exhausted",
        )
    )
    await pausing_runs.understood.wait()
    first.cancel()
    try:
        await first
    except asyncio.CancelledError:
        pass
    harness.now += timedelta(seconds=31)

    outcome = CodingTaskOutcome.CONTINUING
    delivery = 0
    while outcome is CodingTaskOutcome.CONTINUING:
        delivery += 1
        outcome = await CodingTaskRunner(runs=harness.runtime.runs).run(
            task_id=harness.task_id,
            worker_id=f"celery-replacement-{delivery}",
            failure_error_code="worker_retry_exhausted",
        )

    completed = [
        (phase.kind.value, phase.attempt)
        for phase in harness.repository.phases
        if phase.status.value == "completed"
    ]
    assert outcome is CodingTaskOutcome.COMPLETED
    assert completed.count(("understand", 1)) == 1
    assert completed.count(("plan", 1)) == 1
    assert harness.completed_tool_count("fake_understand_0") == 1
