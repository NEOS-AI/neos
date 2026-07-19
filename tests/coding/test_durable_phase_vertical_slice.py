from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from neos.coding.application.run_service import InProcessRunInterrupter
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.domain.phases import SteeringMode
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.runtime import create_coding_runtime
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class CrashAfterToolRepository(InMemoryCodingRunRepository):
    def __init__(self, tool_call_id: str | None) -> None:
        super().__init__()
        self._crash_after = tool_call_id
        self._crashed = False

    async def record_tool_result(self, **record) -> None:
        await super().record_tool_result(**record)
        if record["tool_call_id"] == self._crash_after and not self._crashed:
            self._crashed = True
            raise RuntimeError("simulated worker crash")


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


@dataclass
class DurableCodingHarness:
    crash_after_tool: str | None = None

    def __post_init__(self) -> None:
        self.tasks = InMemoryCodingTaskRepository()
        self.events = InMemoryCodingEventStore()
        self.repository = CrashAfterToolRepository(self.crash_after_tool)
        self.task_service = CodingTaskService(
            self.tasks, self.events, clock=lambda: NOW
        )
        self.service = InMemoryCodingService(self.task_service, self.events)
        self._new_worker()

    def _new_worker(self) -> None:
        self.runtime = create_coding_runtime(
            events=self.service,
            tasks=self.tasks,
            run_repository=self.repository,
            projection_repository=EmptyProjectionRepository(),
            loop=FakeDurableCodingLoop(clock=lambda: NOW),
            interrupter=InProcessRunInterrupter(),
        )
        self.runs = self.runtime.runs

    async def create_task(self, *, owner_id: str, prompt: str):
        task = await self.runtime.events.create_task(
            owner_id=owner_id, prompt=prompt
        )
        await self.runs.start(task_id=task.task_id, instruction=prompt)
        return task

    async def advance_until(self, task_id: str, phase: str) -> None:
        await self.runs.advance_until(task_id=task_id, phase=phase)

    async def advance_one_safe_point(self, task_id: str) -> None:
        await self.runs.advance_one_safe_point(task_id=task_id)

    async def steer(self, **kwargs) -> None:
        await self.runs.steer(**kwargs)

    async def run_until_crash(self, task_id: str) -> None:
        with pytest.raises(RuntimeError, match="simulated worker crash"):
            while True:
                await self.runs.advance_one_safe_point(task_id=task_id)

    async def resume_with_new_worker(self, task_id: str) -> None:
        self._new_worker()
        await self.runs.advance_one_safe_point(task_id=task_id)

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
