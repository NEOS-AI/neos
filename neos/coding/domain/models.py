from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from neos.coding.domain.errors import InvalidTaskTransition


class CodingTaskStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    CLONING = "cloning"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_USER = "waiting_user"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ARCHIVED = "archived"


_ALLOWED_TRANSITIONS: dict[CodingTaskStatus, frozenset[CodingTaskStatus]] = {
    CodingTaskStatus.DRAFT: frozenset({CodingTaskStatus.QUEUED}),
    CodingTaskStatus.QUEUED: frozenset(
        {CodingTaskStatus.PROVISIONING, CodingTaskStatus.CANCELLING}
    ),
    CodingTaskStatus.PROVISIONING: frozenset(
        {CodingTaskStatus.CLONING, CodingTaskStatus.FAILED, CodingTaskStatus.CANCELLING}
    ),
    CodingTaskStatus.CLONING: frozenset(
        {CodingTaskStatus.READY, CodingTaskStatus.FAILED, CodingTaskStatus.CANCELLING}
    ),
    CodingTaskStatus.READY: frozenset(
        {CodingTaskStatus.RUNNING, CodingTaskStatus.CANCELLING, CodingTaskStatus.EXPIRED}
    ),
    CodingTaskStatus.RUNNING: frozenset(
        {
            CodingTaskStatus.WAITING_APPROVAL,
            CodingTaskStatus.WAITING_USER,
            CodingTaskStatus.PAUSING,
            CodingTaskStatus.COMPLETED,
            CodingTaskStatus.FAILED,
            CodingTaskStatus.CANCELLING,
        }
    ),
    CodingTaskStatus.WAITING_APPROVAL: frozenset(
        {CodingTaskStatus.RUNNING, CodingTaskStatus.CANCELLING, CodingTaskStatus.EXPIRED}
    ),
    CodingTaskStatus.WAITING_USER: frozenset(
        {CodingTaskStatus.RUNNING, CodingTaskStatus.CANCELLING, CodingTaskStatus.EXPIRED}
    ),
    CodingTaskStatus.PAUSING: frozenset(
        {CodingTaskStatus.PAUSED, CodingTaskStatus.FAILED}
    ),
    CodingTaskStatus.PAUSED: frozenset(
        {CodingTaskStatus.QUEUED, CodingTaskStatus.CANCELLING, CodingTaskStatus.EXPIRED}
    ),
    CodingTaskStatus.CANCELLING: frozenset(
        {CodingTaskStatus.CANCELLED, CodingTaskStatus.FAILED}
    ),
    CodingTaskStatus.FAILED: frozenset(
        {CodingTaskStatus.QUEUED, CodingTaskStatus.ARCHIVED}
    ),
    CodingTaskStatus.COMPLETED: frozenset({CodingTaskStatus.ARCHIVED}),
    CodingTaskStatus.CANCELLED: frozenset({CodingTaskStatus.ARCHIVED}),
    CodingTaskStatus.EXPIRED: frozenset({CodingTaskStatus.ARCHIVED}),
    CodingTaskStatus.ARCHIVED: frozenset(),
}

TERMINAL_TASK_STATUSES = frozenset(
    {
        CodingTaskStatus.COMPLETED,
        CodingTaskStatus.FAILED,
        CodingTaskStatus.CANCELLED,
        CodingTaskStatus.ARCHIVED,
    }
)


@dataclass(frozen=True, slots=True)
class CodingTask:
    task_id: str
    owner_id: str
    prompt: str
    status: CodingTaskStatus
    version: int
    last_seq: int
    created_at: datetime
    updated_at: datetime


def transition_task(
    task: CodingTask,
    target: CodingTaskStatus,
    now: datetime,
) -> CodingTask:
    if target not in _ALLOWED_TRANSITIONS[task.status]:
        raise InvalidTaskTransition(
            f"cannot transition coding task from {task.status.value} to {target.value}"
        )
    return replace(task, status=target, version=task.version + 1, updated_at=now)

