import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import uuid4

from neos.coding.domain.events import CodingEvent


@dataclass(frozen=True, slots=True)
class WsTicket:
    owner_id: str
    task_id: str
    expires_at: datetime


class InMemoryWsTicketStore:
    """Bounded-by-expiry single-process ticket store for development and tests."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ttl: timedelta = timedelta(seconds=30),
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._tickets: dict[str, WsTicket] = {}
        self._lock = asyncio.Lock()

    @property
    def expires_in(self) -> int:
        return int(self._ttl.total_seconds())

    @property
    def pending_count(self) -> int:
        return len(self._tickets)

    def _sweep_expired(self, now: datetime) -> None:
        expired = [
            token
            for token, ticket in self._tickets.items()
            if ticket.expires_at <= now
        ]
        for token in expired:
            self._tickets.pop(token, None)

    async def issue(self, *, owner_id: str, task_id: str) -> str:
        token = f"cwt_{uuid4().hex}"
        async with self._lock:
            now = self._clock()
            self._sweep_expired(now)
            self._tickets[token] = WsTicket(
                owner_id=owner_id,
                task_id=task_id,
                expires_at=now + self._ttl,
            )
        return token

    async def consume(self, token: str, *, task_id: str) -> str | None:
        async with self._lock:
            now = self._clock()
            self._sweep_expired(now)
            ticket = self._tickets.pop(token, None)
            if ticket is None or ticket.task_id != task_id:
                return None
            return ticket.owner_id


class InMemoryCodingEventSubscription:
    def __init__(
        self,
        *,
        task_id: str,
        queue: asyncio.Queue[CodingEvent],
        transport: "InProcessCodingEventBroker",
    ) -> None:
        self.task_id = task_id
        self._queue = queue
        self._transport = transport
        self._closed = False

    async def get(self) -> CodingEvent:
        return await self._queue.get()

    def empty(self) -> bool:
        return self._queue.empty()

    def put_nowait(self, event: CodingEvent) -> None:
        self._queue.put_nowait(event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._transport._remove(self)


class InProcessCodingEventBroker:
    """Process-local live fan-out; durable replay remains PostgreSQL-backed."""

    def __init__(self, *, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[
            str, set[InMemoryCodingEventSubscription]
        ] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(self, task_id: str) -> InMemoryCodingEventSubscription:
        if self._closed:
            raise RuntimeError("coding event transport is closed")
        subscription = InMemoryCodingEventSubscription(
            task_id=task_id,
            queue=asyncio.Queue(maxsize=self._queue_size),
            transport=self,
        )
        async with self._lock:
            if self._closed:
                raise RuntimeError("coding event transport is closed")
            self._subscribers[task_id].add(subscription)
        return subscription

    async def _remove(self, subscription: InMemoryCodingEventSubscription) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(subscription.task_id)
            if subscribers is None:
                return
            subscribers.discard(subscription)
            if not subscribers:
                self._subscribers.pop(subscription.task_id, None)

    async def unsubscribe(
        self, task_id: str, subscription: InMemoryCodingEventSubscription
    ) -> None:
        del task_id
        await subscription.close()

    async def publish(self, event: CodingEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.task_id, ()))
        for subscription in subscribers:
            try:
                subscription.put_nowait(event)
            except asyncio.QueueFull:
                await subscription.close()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = [
                subscription
                for subscribers in self._subscribers.values()
                for subscription in subscribers
            ]
            self._subscribers.clear()
        for subscription in subscriptions:
            subscription._closed = True

    def subscriber_count(self, task_id: str) -> int:
        return len(self._subscribers.get(task_id, ()))
