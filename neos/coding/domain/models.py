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

ARCHIVABLE_TASK_STATUSES = frozenset(
    {
        CodingTaskStatus.FAILED,
        CodingTaskStatus.COMPLETED,
        CodingTaskStatus.CANCELLED,
        CodingTaskStatus.EXPIRED,
    }
)


class CodingTaskMode(StrEnum):
    """누가 보고 있는가 (로드맵 K9).

    `INTERACTIVE` 는 사람이 Code UI 에서 보고 승인한다. `AUTONOMOUS` 는 아무도
    보지 않는다 -- 승인을 기다리면 영원히 기다리므로 REQUIRE_APPROVAL 은
    거절로 접힌다(D-L1). 태스크에 붙는 이유는 재개·워커 이관에서도 같아야
    하기 때문이다.
    """

    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"
    #: 트랙 Q1 -- 아무도 시키지 않은 일(선제적 조사). 보는 사람이 없고(autonomous
    #: 처럼 접힌다) 천장이 READ_ONLY 다. 결과는 메모·알림 후보뿐이다.
    BACKGROUND = "background"


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
    mode: CodingTaskMode = CodingTaskMode.INTERACTIVE


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

