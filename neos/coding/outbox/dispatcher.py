import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

from neos.coding.domain.events import CodingEvent
from neos.coding.outbox.models import ClaimedOutboxEvent


logger = logging.getLogger(__name__)


class OutboxRepository(Protocol):
    async def claim_batch(
        self, *, limit: int, now: datetime, stale_before: datetime
    ) -> list[ClaimedOutboxEvent]: ...

    async def mark_published(
        self, outbox_id: str, *, published_at: datetime
    ) -> None: ...

    async def mark_failed(
        self, outbox_id: str, *, error: str, next_attempt_at: datetime
    ) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: CodingEvent) -> None: ...


def retry_delay(
    attempt_count: int, base: float = 0.5, cap: float = 60.0
) -> float:
    if attempt_count < 1:
        raise ValueError("attempt_count must be positive")
    return min(cap, base * 2 ** (attempt_count - 1))


class CodingOutboxDispatcher:
    def __init__(
        self,
        repository: OutboxRepository,
        publisher: EventPublisher,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch_size: int = 100,
        poll_interval: float = 0.5,
        claim_lease: timedelta = timedelta(seconds=30),
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._clock = clock
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._claim_lease = claim_lease
        self._wake_event = asyncio.Event()

    async def run_once(self) -> int:
        now = self._clock()
        claimed = await self._repository.claim_batch(
            limit=self._batch_size,
            now=now,
            stale_before=now - self._claim_lease,
        )
        published = 0
        for item in claimed:
            try:
                await self._publisher.publish(item.event)
            except Exception as error:
                delay = retry_delay(item.attempt_count + 1)
                await self._repository.mark_failed(
                    item.outbox_id,
                    error=str(error),
                    next_attempt_at=now + timedelta(seconds=delay),
                )
            else:
                await self._repository.mark_published(
                    item.outbox_id, published_at=self._clock()
                )
                published += 1
        return published

    def wake(self) -> None:
        self._wake_event.set()

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Coding outbox dispatch iteration failed")
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(), timeout=self._poll_interval
                )
            except TimeoutError:
                pass
            finally:
                self._wake_event.clear()
