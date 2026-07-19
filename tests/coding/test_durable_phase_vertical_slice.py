import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.application.run_service import InProcessRunInterrupter
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.domain.phases import SteeringMode
from neos.coding.domain.durability import RunAlreadyLeased
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.runtime import create_coding_runtime
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class CrashAfterToolRepository(InMemoryCodingRunRepository):
    def __init__(
        self,
        tool_call_id: str | None,
        *,
        block_after_lease: bool = False,
    ) -> None:
        super().__init__()
        self._crash_after = tool_call_id
        self._crashed = False
        self._block_after_lease = block_after_lease
        self.first_worker_has_lease = asyncio.Event()
        self.release_first_worker = asyncio.Event()

    async def acquire_execution_lease(self, **kwargs):
        lease = await super().acquire_execution_lease(**kwargs)
        if (
            lease is not None
            and self._block_after_lease
            and kwargs["worker_id"] == "worker-a"
            and not self.first_worker_has_lease.is_set()
        ):
            self.first_worker_has_lease.set()
            await self.release_first_worker.wait()
        return lease

    async def complete_tool_execution(self, claim, *, result, now):
        event = await super().complete_tool_execution(
            claim, result=result, now=now
        )
        if claim.tool_call_id == self._crash_after and not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated worker crash")
        return event


class InMemoryCodingService:
    def __init__(self, task_service, event_store) -> None:
        self._tasks = task_service
        self._events = event_store

    async def create_task(self, **kwargs):
        return await self._tasks.create_task(**kwargs)

    async def append(self, **kwargs):
        return await self._events.append(**kwargs)


class EmptyProjectionRepository:
    async def get_owned_snapshot(self, task_id: str, owner_id: str):
        return None


class RecordingLoop(FakeDurableCodingLoop):
    def __init__(self, *, clock) -> None:
        super().__init__(clock=clock)
        self.inputs = []

    async def run(self, input, checkpoint, deps):
        self.inputs.append(input)
        async for event in super().run(input, checkpoint, deps):
            yield event


@dataclass
class DurableCodingHarness:
    crash_after_tool: str | None = None
    block_first_worker_after_lease: bool = False
    metrics: object | None = None

    def __post_init__(self) -> None:
        self.now = NOW
        self.tasks = InMemoryCodingTaskRepository()
        self.events = InMemoryCodingEventStore()
        self.repository = CrashAfterToolRepository(
            self.crash_after_tool,
            block_after_lease=self.block_first_worker_after_lease,
        )
        self.loop = RecordingLoop(clock=lambda: self.now)
        self.task_service = CodingTaskService(
            self.tasks, self.events, clock=lambda: self.now
        )
        self.service = InMemoryCodingService(self.task_service, self.events)
        self._new_worker()

    def _new_worker(self) -> None:
        self.runtime = create_coding_runtime(
            events=self.service,
            tasks=self.tasks,
            run_repository=self.repository,
            projection_repository=EmptyProjectionRepository(),
            loop=self.loop,
            interrupter=InProcessRunInterrupter(),
            clock=lambda: self.now,
            metrics_collector=self.metrics,
        )
        self.runs = self.runtime.runs

    async def create_task(self, *, owner_id: str, prompt: str):
        task = await self.runtime.events.create_task(
            owner_id=owner_id, prompt=prompt
        )
        await self.runs.start(task_id=task.task_id, instruction=prompt)
        return task

    async def advance_until(self, task_id: str, phase: str) -> None:
        await self.runs.advance_until(
            task_id=task_id, phase=phase, worker_id="worker-a"
        )

    async def advance_one_safe_point(
        self, task_id: str, worker_id: str = "worker-a"
    ) -> None:
        await self.runs.advance_one_safe_point(
            task_id=task_id, worker_id=worker_id
        )

    async def steer(self, **kwargs) -> None:
        await self.runs.steer(**kwargs)

    async def run_until_crash(self, task_id: str) -> None:
        with pytest.raises(RuntimeError, match="simulated worker crash"):
            while True:
                await self.runs.advance_one_safe_point(
                    task_id=task_id, worker_id="worker-a"
                )

    async def resume_with_new_worker(self, task_id: str) -> None:
        self.now += timedelta(seconds=31)
        self._new_worker()
        await self.runs.advance_one_safe_point(
            task_id=task_id, worker_id="worker-b"
        )

    def tool_execution_count(self, tool_call_id: str) -> int:
        return sum(
            call["tool_call_id"] == tool_call_id
            for call in self.repository.tool_execution_calls
        )


async def test_safe_point_steer_restarts_append_only_phase_history() -> None:
    harness = DurableCodingHarness()
    task = await harness.create_task(owner_id="u1", prompt="Fix it")
    await harness.advance_until(task.task_id, phase="implement")

    await harness.steer(
        task_id=task.task_id,
        owner_id="u1",
        instruction="Inspect cache first",
        mode=SteeringMode.SAFE_POINT,
    )
    await harness.advance_one_safe_point(task.task_id)

    assert [(phase.kind.value, phase.attempt) for phase in harness.repository.phases][
        -1
    ] == ("understand", 2)
    assert harness.repository.checkpoints[-1].loop_state["pending_instruction"] is None
    assert harness.repository.applied_steering[-1].applied_checkpoint_id


async def test_worker_crash_after_tool_completion_does_not_repeat_tool() -> None:
    harness = DurableCodingHarness(crash_after_tool="fake_implement_2")
    task = await harness.create_task(owner_id="u1", prompt="Fix it")

    await harness.run_until_crash(task.task_id)
    await harness.resume_with_new_worker(task.task_id)

    assert harness.tool_execution_count("fake_implement_2") == 1
    assert harness.repository.active_run.status.value == "running"


async def test_new_worker_restores_instruction_from_checkpoint() -> None:
    harness = DurableCodingHarness()
    task = await harness.create_task(owner_id="u1", prompt="Fix the cache")
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")

    harness._new_worker()
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-b")

    assert harness.loop.inputs[-1].instruction == "Fix the cache"
    assert harness.repository.checkpoints[-1].loop_state[
        "current_instruction"
    ] == "Fix the cache"


async def test_two_workers_cannot_advance_same_task() -> None:
    harness = DurableCodingHarness(block_first_worker_after_lease=True)
    task = await harness.create_task(owner_id="u1", prompt="Fix it")
    first = asyncio.create_task(
        harness.advance_one_safe_point(task.task_id, worker_id="worker-a")
    )
    await harness.repository.first_worker_has_lease.wait()

    with pytest.raises(RunAlreadyLeased):
        await harness.advance_one_safe_point(task.task_id, worker_id="worker-b")

    harness.repository.release_first_worker.set()
    await first
    completed = [
        phase
        for phase in harness.repository.phases
        if phase.kind.value == "understand"
        and phase.attempt == 1
        and phase.status.value == "completed"
    ]
    assert len(completed) == 1
