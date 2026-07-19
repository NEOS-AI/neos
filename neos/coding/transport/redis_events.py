import asyncio
import contextlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from neos.coding.domain.events import CodingEvent
from neos.coding.transport.base import (
    CodingEventSubscriptionClosed,
    CodingEventSubscriptionOverloaded,
)


class RedisCodingEventSubscription:
    def __init__(
        self,
        *,
        task_id: str,
        queue_size: int,
        transport: "RedisCodingEventTransport",
    ) -> None:
        self.task_id = task_id
        self._queue: asyncio.Queue[CodingEvent] = asyncio.Queue(maxsize=queue_size)
        self._transport = transport
        self._closed = False
        self._error: CodingEventSubscriptionClosed | None = None
        self._closed_event = asyncio.Event()

    async def get(self) -> CodingEvent:
        if self._error is not None:
            raise self._error
        event_task = asyncio.create_task(self._queue.get())
        closed_task = asyncio.create_task(self._closed_event.wait())
        done, pending = await asyncio.wait(
            {event_task, closed_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if closed_task in done:
            with contextlib.suppress(asyncio.CancelledError):
                await event_task
            raise self._error or CodingEventSubscriptionClosed("subscription closed")
        closed_task.cancel()
        return event_task.result()

    def _offer(self, event: CodingEvent) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._mark_closed(
                CodingEventSubscriptionOverloaded(
                    "local coding event subscription queue overflowed"
                )
            )

    def _mark_closed(self, error: CodingEventSubscriptionClosed) -> None:
        if self._closed:
            return
        self._closed = True
        self._error = error
        self._closed_event.set()

    async def close(self) -> None:
        if self._closed:
            return
        self._mark_closed(CodingEventSubscriptionClosed("subscription closed"))
        await self._transport._remove(self)


@dataclass(slots=True)
class _TaskEntry:
    channel: str
    pubsub: Any
    subscriptions: set[RedisCodingEventSubscription] = field(default_factory=set)
    listener: asyncio.Task[None] | None = None


class RedisCodingEventTransport:
    """Cross-worker live fan-out backed by Redis Pub/Sub."""

    def __init__(
        self,
        redis_client: Any,
        *,
        channel_prefix: str = "neos:coding:events",
        queue_size: int = 256,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._redis = redis_client
        self._channel_prefix = channel_prefix.rstrip(":")
        self._queue_size = queue_size
        self._entries: dict[str, _TaskEntry] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    def _channel(self, task_id: str) -> str:
        return f"{self._channel_prefix}:{task_id}"

    async def publish(self, event: CodingEvent) -> None:
        if self._closed:
            raise RuntimeError("coding event transport is closed")
        await self._redis.publish(self._channel(event.task_id), _encode_event(event))

    async def subscribe(self, task_id: str) -> RedisCodingEventSubscription:
        async with self._lock:
            if self._closed:
                raise RuntimeError("coding event transport is closed")
            entry = self._entries.get(task_id)
            if entry is None:
                pubsub = self._redis.pubsub()
                entry = _TaskEntry(channel=self._channel(task_id), pubsub=pubsub)
                await pubsub.subscribe(entry.channel)
                self._entries[task_id] = entry
                entry.listener = asyncio.create_task(self._listen(task_id, entry))
            subscription = RedisCodingEventSubscription(
                task_id=task_id,
                queue_size=self._queue_size,
                transport=self,
            )
            entry.subscriptions.add(subscription)
            return subscription

    async def _listen(self, task_id: str, entry: _TaskEntry) -> None:
        failure: CodingEventSubscriptionClosed | None = None
        try:
            while True:
                message = await entry.pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None or message.get("type") != "message":
                    continue
                event = _decode_event(message.get("data"))
                for subscription in tuple(entry.subscriptions):
                    subscription._offer(event)
                    if subscription._closed:
                        entry.subscriptions.discard(subscription)
                if not entry.subscriptions:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = CodingEventSubscriptionClosed(
                f"Redis coding event listener failed: {type(exc).__name__}"
            )
        finally:
            if failure is not None:
                for subscription in tuple(entry.subscriptions):
                    subscription._mark_closed(failure)
            await self._cleanup_entry(task_id, entry)

    async def _remove(self, subscription: RedisCodingEventSubscription) -> None:
        listener: asyncio.Task[None] | None = None
        async with self._lock:
            entry = self._entries.get(subscription.task_id)
            if entry is None:
                return
            entry.subscriptions.discard(subscription)
            if not entry.subscriptions:
                listener = entry.listener
        if listener is not None:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await self._cleanup_entry(subscription.task_id, entry)

    async def _cleanup_entry(self, task_id: str, entry: _TaskEntry) -> None:
        async with self._lock:
            if self._entries.get(task_id) is not entry:
                return
            self._entries.pop(task_id, None)
        with contextlib.suppress(Exception):
            await entry.pubsub.unsubscribe(entry.channel)
        with contextlib.suppress(Exception):
            await entry.pubsub.aclose()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            entries = tuple(self._entries.values())
            for entry in entries:
                for subscription in tuple(entry.subscriptions):
                    subscription._mark_closed(
                        CodingEventSubscriptionClosed("transport closed")
                    )
            listeners = tuple(
                entry.listener for entry in entries if entry.listener is not None
            )
        for listener in listeners:
            listener.cancel()
        for listener in listeners:
            with contextlib.suppress(asyncio.CancelledError):
                await listener


def _encode_event(event: CodingEvent) -> str:
    record = asdict(event)
    record["created_at"] = event.created_at.isoformat()
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def _decode_event(raw: Any) -> CodingEvent:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError("coding event envelope must be an object")
    created_at = datetime.fromisoformat(record["created_at"])
    return CodingEvent(
        version=int(record["version"]),
        task_id=str(record["task_id"]),
        seq=int(record["seq"]),
        event_id=str(record["event_id"]),
        type=str(record["type"]),
        payload=dict(record["payload"]),
        created_at=created_at,
        run_id=record.get("run_id"),
        turn_id=record.get("turn_id"),
        tool_call_id=record.get("tool_call_id"),
        checkpoint_id=record.get("checkpoint_id"),
    )
