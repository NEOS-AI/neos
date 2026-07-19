from datetime import UTC, datetime

import pytest

from neos.coding.domain.errors import InvalidTaskTransition
from neos.coding.domain.models import (
    CodingTask,
    CodingTaskStatus,
    transition_task,
)


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)


def make_task(status: CodingTaskStatus) -> CodingTask:
    return CodingTask(
        task_id="ct_01",
        owner_id="user_01",
        prompt="Fix the failing test",
        status=status,
        version=3,
        last_seq=0,
        created_at=NOW,
        updated_at=NOW,
    )


def test_queued_task_can_enter_provisioning() -> None:
    task = make_task(CodingTaskStatus.QUEUED)

    changed = transition_task(task, CodingTaskStatus.PROVISIONING, NOW)

    assert changed.status is CodingTaskStatus.PROVISIONING
    assert changed.version == 4
    assert task.status is CodingTaskStatus.QUEUED


def test_completed_task_cannot_return_to_running() -> None:
    with pytest.raises(InvalidTaskTransition, match="completed.*running"):
        transition_task(
            make_task(CodingTaskStatus.COMPLETED),
            CodingTaskStatus.RUNNING,
            NOW,
        )


def test_transition_to_same_status_is_rejected() -> None:
    with pytest.raises(InvalidTaskTransition, match="queued.*queued"):
        transition_task(
            make_task(CodingTaskStatus.QUEUED),
            CodingTaskStatus.QUEUED,
            NOW,
        )

