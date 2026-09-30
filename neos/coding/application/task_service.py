import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Callable, Protocol
from uuid import uuid4

from neos.coding.domain.errors import InvalidTaskTransition
from neos.coding.domain.models import (
    ARCHIVABLE_TASK_STATUSES,
    CodingTask,
    CodingTaskMode,
    CodingTaskStatus,
    transition_task,
)
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
        task = self._tasks.get(task_id)
        if task is None or task.owner_id != owner_id:
            return False
        if task.status is CodingTaskStatus.ARCHIVED:
            return True
        now = datetime.now(UTC)
        self._tasks[task_id] = transition_task(
            task, CodingTaskStatus.ARCHIVED, now
        )
        self.mark_deleted(task_id, now)
        return True

    async def delete(self, task_id: str, owner_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.owner_id != owner_id:
            return False
        self._tasks.pop(task_id, None)
        self._last_activity_at.pop(task_id, None)
        self._deleted_at.pop(task_id, None)
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


def task_created_payload(task: CodingTask) -> dict[str, str]:
    """`task.created` 의 payload. 두 서비스(메모리·Postgres)가 함께 쓴다.

    `actor` 는 에이전트가 연 태스크에만 있다(Q13 설계 §5) -- 없으면 사람이다.
    """
    payload = {
        "status": task.status.value,
        "prompt": task.prompt,
        "mode": task.mode.value,
    }
    if task.agent_id is not None:
        payload["actor"] = f"agent:{task.agent_id}"
    return payload


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
        self,
        *,
        owner_id: str,
        prompt: str,
        task_id: str | None = None,
        mode: CodingTaskMode = CodingTaskMode.INTERACTIVE,
        agent_id: str | None = None,
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
            mode=mode,
            agent_id=agent_id,
        )
        await self.tasks.create(task)
        event = await self.events.append(
            task_id=task.task_id,
            event_type="task.created",
            payload=task_created_payload(task),
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
        task = await self._owned_including_archived(task_id, owner_id)
        if task is None:
            return False
        if task.status is not CodingTaskStatus.ARCHIVED:
            if task.status not in ARCHIVABLE_TASK_STATUSES:
                raise InvalidTaskTransition(
                    f"cannot transition coding task from {task.status.value} "
                    "to archived"
                )
            archiver = getattr(self.tasks, "archive", None)
            if archiver is not None:
                await archiver(task_id, owner_id)
            else:
                marker = getattr(self.tasks, "mark_deleted", None)
                if marker is not None:
                    marker(task_id)
        await self._purge_parent_subagents(task_id)
        return True

    async def delete(self, task_id: str, owner_id: str) -> bool:
        raw = await self._lookup_task(task_id)
        if raw is None:
            await self._purge_parent_subagents(task_id)
            return False
        if raw.owner_id != owner_id:
            return False
        deleter = getattr(self.tasks, "delete", None)
        if deleter is not None:
            await deleter(task_id, owner_id)
        else:
            marker = getattr(self.tasks, "mark_deleted", None)
            if marker is not None:
                marker(task_id)
        await self._purge_parent_subagents(task_id)
        return True

    async def fail(self, task_id: str, owner_id: str) -> bool:
        task = await self.tasks.get_owned(task_id, owner_id)
        if task is None:
            return False
        if task.status is not CodingTaskStatus.FAILED:
            task = transition_task(task, CodingTaskStatus.FAILED, self._clock())
            await self.tasks.save(task)
        await self._purge_parent_subagents(task_id)
        return True

    async def _purge_parent_subagents(self, task_id: str) -> None:
        if self._subagents is None:
            return
        from neos.subagent.types import ParentKind

        await self._subagents.delete_for_parent(ParentKind.CODING, task_id)

    async def _lookup_task(self, task_id: str) -> CodingTask | None:
        getter = getattr(self.tasks, "get", None)
        if getter is not None:
            return await getter(task_id)
        return None

    async def _owned_including_archived(
        self, task_id: str, owner_id: str
    ) -> CodingTask | None:
        getter = getattr(self.tasks, "get", None)
        if getter is not None:
            task = await getter(task_id)
            if task is not None and task.owner_id == owner_id:
                return task
        return await self.tasks.get_owned(task_id, owner_id)
