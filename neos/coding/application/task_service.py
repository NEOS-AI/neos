from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Callable, Protocol
from uuid import uuid4

from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.events.store import InMemoryCodingEventStore


class TaskRepository(Protocol):
    async def create(self, task: CodingTask) -> CodingTask: ...
    async def get_owned(self, task_id: str, owner_id: str) -> CodingTask | None: ...
    async def save(self, task: CodingTask) -> CodingTask: ...


class InMemoryCodingTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, CodingTask] = {}

    async def create(self, task: CodingTask) -> CodingTask:
        if task.task_id in self._tasks:
            raise ValueError(f"coding task already exists: {task.task_id}")
        self._tasks[task.task_id] = task
        return task

    async def get_owned(self, task_id: str, owner_id: str) -> CodingTask | None:
        task = self._tasks.get(task_id)
        return task if task is not None and task.owner_id == owner_id else None

    async def save(self, task: CodingTask) -> CodingTask:
        self._tasks[task.task_id] = task
        return task


@dataclass(frozen=True, slots=True)
class CodingTaskSnapshot:
    task: CodingTask
    head_seq: int


class CodingTaskService:
    def __init__(
        self,
        tasks: TaskRepository,
        events: InMemoryCodingEventStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.tasks = tasks
        self.events = events
        self._clock = clock

    async def create_task(
        self, *, owner_id: str, prompt: str, task_id: str | None = None
    ) -> CodingTask:
        now = self._clock()
        task = CodingTask(
            task_id=task_id or f"ct_{uuid4().hex}",
            owner_id=owner_id,
            prompt=prompt,
            status=CodingTaskStatus.QUEUED,
            version=1,
            last_seq=0,
            created_at=now,
            updated_at=now,
        )
        await self.tasks.create(task)
        event = await self.events.append(
            task_id=task.task_id,
            event_type="task.created",
            payload={"status": task.status.value, "prompt": prompt},
            now=now,
        )
        task = replace(task, last_seq=event.seq)
        return await self.tasks.save(task)

    async def snapshot(
        self, task_id: str, owner_id: str
    ) -> CodingTaskSnapshot | None:
        task = await self.tasks.get_owned(task_id, owner_id)
        if task is None:
            return None
        return CodingTaskSnapshot(
            task=task, head_seq=await self.events.head_seq(task_id)
        )
