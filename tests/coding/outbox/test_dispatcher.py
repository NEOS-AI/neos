import asyncio
from datetime import UTC, datetime

import pytest

from neos.coding.domain.events import make_event
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher, retry_delay
from neos.coding.outbox.models import ClaimedOutboxEvent


NOW = datetime(2026, 7, 18, 11, 0, tzinfo=UTC)


def claimed(outbox_id: str, task_id: str, seq: int, attempt_count: int = 0):
    return ClaimedOutboxEvent(
        outbox_id=outbox_id,
        attempt_count=attempt_count,
        event=make_event(
            task_id=task_id,
            seq=seq,
            event_type="text.delta",
            payload={"delta": task_id},
            now=NOW,
            event_id=f"ce_{task_id}_{seq}",
        ),
    )


class FakeRepository:
    def __init__(self, batch):
        self.batch = list(batch)
        self.timeline: list[str] = []
        self.failures: list[tuple[str, str, datetime]] = []
        self.claim_calls = 0

    async def claim_batch(self, **_):
        self.claim_calls += 1
        batch, self.batch = self.batch, []
        return batch

    async def mark_published(self, outbox_id, *, published_at):
        self.timeline.append(f"published:{outbox_id}")

    async def mark_failed(self, outbox_id, *, error, next_attempt_at):
        self.failures.append((outbox_id, error, next_attempt_at))


class FakePublisher:
    def __init__(self, repository: FakeRepository, fail_task: str | None = None):
        self.repository = repository
        self.fail_task = fail_task

    async def publish(self, event):
        self.repository.timeline.append(f"publish:{event.task_id}")
        if event.task_id == self.fail_task:
            raise RuntimeError("publisher unavailable")


def test_retry_delay_is_exponential_and_capped() -> None:
    assert retry_delay(1) == 0.5
    assert retry_delay(2) == 1.0
    assert retry_delay(20) == 60.0


async def test_run_once_acknowledges_only_after_publish() -> None:
    repository = FakeRepository([claimed("co_1", "ct_1", 1)])
    dispatcher = CodingOutboxDispatcher(
        repository, FakePublisher(repository), clock=lambda: NOW
    )

    assert await dispatcher.run_once() == 1
    assert repository.timeline == ["publish:ct_1", "published:co_1"]


async def test_failure_is_retried_without_blocking_unrelated_task() -> None:
    repository = FakeRepository(
        [claimed("co_1", "ct_bad", 1), claimed("co_2", "ct_good", 1)]
    )
    dispatcher = CodingOutboxDispatcher(
        repository, FakePublisher(repository, fail_task="ct_bad"), clock=lambda: NOW
    )

    assert await dispatcher.run_once() == 1
    assert repository.timeline == [
        "publish:ct_bad",
        "publish:ct_good",
        "published:co_2",
    ]
    assert repository.failures[0][0:2] == ("co_1", "publisher unavailable")
    assert (repository.failures[0][2] - NOW).total_seconds() == 0.5


async def test_run_propagates_cancellation() -> None:
    repository = FakeRepository([])
    dispatcher = CodingOutboxDispatcher(
        repository,
        FakePublisher(repository),
        clock=lambda: NOW,
        poll_interval=60,
    )
    task = asyncio.create_task(dispatcher.run())
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
