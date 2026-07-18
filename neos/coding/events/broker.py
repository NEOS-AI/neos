import asyncio
from collections import defaultdict

from neos.coding.domain.events import CodingEvent


class InProcessCodingEventBroker:
    """Process-local live fan-out; durable replay remains PostgreSQL-backed."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[CodingEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str) -> asyncio.Queue[CodingEvent]:
        subscription: asyncio.Queue[CodingEvent] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers[task_id].add(subscription)
        return subscription

    async def unsubscribe(
        self, task_id: str, subscription: asyncio.Queue[CodingEvent]
    ) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(task_id)
            if subscribers is None:
                return
            subscribers.discard(subscription)
            if not subscribers:
                self._subscribers.pop(task_id, None)

    async def publish(self, event: CodingEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.task_id, ()))
        for subscription in subscribers:
            try:
                subscription.put_nowait(event)
            except asyncio.QueueFull:
                # A slow client must reconnect and use durable replay.
                await self.unsubscribe(event.task_id, subscription)

    def subscriber_count(self, task_id: str) -> int:
        return len(self._subscribers.get(task_id, ()))


coding_event_broker = InProcessCodingEventBroker()
