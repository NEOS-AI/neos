import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Callable, Protocol
from uuid import uuid4

from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.events.store import InMemoryCodingEventStore


logger = logging.getLogger(__name__)


class TaskRepository(Protocol):
    async def create(self, task: CodingTask) -> CodingTask: ...
    async def get(self, task_id: str) -> CodingTask | None: ...
    async def get_owned(self, task_id: str, owner_id: str) -> CodingTask | None: ...
    async def save(self, task: CodingTask) -> CodingTask: ...
    async def list_owned(self, owner_id: str, *, limit: int) -> list[CodingTask]: ...


def clamp_task_list_limit(limit: int) -> int:
    return max(1, min(int(limit), 50))


class InMemoryCodingTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, CodingTask] = {}
        self._last_activity_at: dict[str, datetime] = {}
        self._deleted_at: dict[str, datetime] = {}

    async def create(self, task: CodingTask) -> CodingTask:
        if task.task_id in self._tasks:
            raise ValueError(f"coding task already exists: {task.task_id}")
        self._tasks[task.task_id] = task
        self._last_activity_at[task.task_id] = task.updated_at
        return task

    async def get(self, task_id: str) -> CodingTask | None:
        return self._tasks.get(task_id)

    async def get_owned(self, task_id: str, owner_id: str) -> CodingTask | None:
        task = self._tasks.get(task_id)
        return task if task is not None and task.owner_id == owner_id else None

    async def save(self, task: CodingTask) -> CodingTask:
        self._tasks[task.task_id] = task
        current = self._last_activity_at.get(task.task_id)
        if current is None or task.updated_at >= current:
            self._last_activity_at[task.task_id] = task.updated_at
        return task

    def record_activity(self, task_id: str, when: datetime) -> None:
        self._last_activity_at[task_id] = when

    def mark_deleted(self, task_id: str, when: datetime | None = None) -> None:
        self._deleted_at[task_id] = when or datetime.now(UTC)

    async def archive(self, task_id: str, owner_id: str) -> bool:
        task = await self.get_owned(task_id, owner_id)
        if task is None:
            return False
        now = datetime.now(UTC)
        self.mark_deleted(task_id, now)
        self._tasks[task_id] = replace(
            task, status=CodingTaskStatus.ARCHIVED, updated_at=now
        )
        return True

    async def list_owned(self, owner_id: str, *, limit: int) -> list[CodingTask]:
        owned = [
            task
            for task in self._tasks.values()
            if task.owner_id == owner_id and task.task_id not in self._deleted_at
        ]
        owned.sort(
            key=lambda task: (
                self._last_activity_at.get(task.task_id, task.updated_at),
                task.task_id,
            ),
            reverse=True,
        )
        return owned[: clamp_task_list_limit(limit)]


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
        subagents=None,
    ) -> None:
        self.tasks = tasks
        self.events = events
        self._clock = clock
        self._task_created_notifier: Callable[[str], bool | None] | None = None
        self._subagents = subagents

    def set_task_created_notifier(
        self, notifier: Callable[[str], bool | None] | None
    ) -> None:
        self._task_created_notifier = notifier

    def _notify_task_created(self, task_id: str) -> None:
        if self._task_created_notifier is None:
            return
        try:
            self._task_created_notifier(task_id)
        except Exception:
            logger.exception(
                "Coding task wake notification failed",
                extra={"task_id": task_id},
            )

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
        task = await self.tasks.save(task)
        self._notify_task_created(task.task_id)
        return task

    async def snapshot(
        self, task_id: str, owner_id: str
    ) -> CodingTaskSnapshot | None:
        task = await self.tasks.get_owned(task_id, owner_id)
        if task is None:
            return None
        return CodingTaskSnapshot(
            task=task, head_seq=await self.events.head_seq(task_id)
        )

    async def list_owned(self, owner_id: str, *, limit: int) -> list[CodingTask]:
        return await self.tasks.list_owned(
            owner_id, limit=clamp_task_list_limit(limit)
        )

    async def archive(self, task_id: str, owner_id: str) -> bool:
        task = await self.tasks.get_owned(task_id, owner_id)
        if task is None:
            return False
        archiver = getattr(self.tasks, "archive", None)
        if archiver is not None:
            ok = await archiver(task_id, owner_id)
        else:
            marker = getattr(self.tasks, "mark_deleted", None)
            if marker is not None:
                marker(task_id)
            ok = True
        if ok and self._subagents is not None:
            from neos.subagent.types import ParentKind

            await self._subagents.delete_for_parent(ParentKind.CODING, task_id)
        return bool(ok)
