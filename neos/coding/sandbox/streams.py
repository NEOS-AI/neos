from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from neos.coding.sandbox.base import (
    ReplayGap,
    SandboxPolicyViolation,
    SandboxStateConflict,
    StreamEvent,
)


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class _Closed:
    pass


@dataclass(frozen=True, slots=True)
class _SubscriberGap:
    evicted_through: int


_CLOSED = _Closed()


class BoundedReplayStream(Generic[T]):
    """A monotonic event stream with bounded history and reconnect replay."""

    def __init__(
        self,
        *,
        max_events: int,
        max_bytes: int,
        size_of: Callable[[T], int],
    ) -> None:
        if max_events < 1 or max_bytes < 1:
            raise SandboxPolicyViolation("stream_limits_must_be_positive")
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._size_of = size_of
        self._events: deque[StreamEvent[T]] = deque()
        self._event_sizes: deque[int] = deque()
        self._subscribers: set[asyncio.Queue[object]] = set()
        self._lock = asyncio.Lock()
        self._cursor = 0
        self._evicted_through = 0
        self._bytes = 0
        self._closed = False

    async def publish(self, value: T) -> StreamEvent[T]:
        size = self._size_of(value)
        if size < 0:
            raise SandboxPolicyViolation("stream_event_size_is_negative")
        async with self._lock:
            if self._closed:
                raise SandboxStateConflict("stream_closed")
            self._cursor += 1
            event = StreamEvent(cursor=self._cursor, value=value)
            self._events.append(event)
            self._event_sizes.append(size)
            self._bytes += size
            self._evict_to_limits()
            for queue in self._subscribers:
                if queue.full():
                    while not queue.empty():
                        queue.get_nowait()
                    queue.put_nowait(_SubscriberGap(self._evicted_through))
                else:
                    queue.put_nowait(event)
            return event

    async def replay(
        self,
        *,
        after_cursor: int,
    ) -> tuple[StreamEvent[T], ...]:
        async with self._lock:
            self._raise_if_gap(after_cursor)
            return tuple(
                event
                for event in self._events
                if event.cursor > after_cursor
            )

    async def subscribe(
        self,
        *,
        after_cursor: int,
    ) -> AsyncIterator[StreamEvent[T]]:
        queue: asyncio.Queue[object] = asyncio.Queue(
            maxsize=self._max_events
        )
        async with self._lock:
            self._raise_if_gap(after_cursor)
            replay = tuple(
                event
                for event in self._events
                if event.cursor > after_cursor
            )
            if self._closed:
                closed = True
            else:
                closed = False
                self._subscribers.add(queue)
        try:
            for event in replay:
                yield event
            if closed:
                return
            while True:
                item = await queue.get()
                if item is _CLOSED:
                    return
                if isinstance(item, _SubscriberGap):
                    raise ReplayGap(
                        "subscriber fell behind bounded replay buffer"
                    )
                yield cast(StreamEvent[T], item)
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            for queue in self._subscribers:
                while queue.full():
                    queue.get_nowait()
                queue.put_nowait(_CLOSED)

    def _evict_to_limits(self) -> None:
        while self._events and (
            len(self._events) > self._max_events
            or self._bytes > self._max_bytes
        ):
            evicted = self._events.popleft()
            self._bytes -= self._event_sizes.popleft()
            self._evicted_through = evicted.cursor

    def _raise_if_gap(self, after_cursor: int) -> None:
        if after_cursor < 0:
            raise SandboxPolicyViolation("stream_cursor_is_negative")
        if after_cursor < self._evicted_through:
            raise ReplayGap(f"cursor {after_cursor} was evicted")
        if after_cursor > self._cursor:
            raise SandboxPolicyViolation("stream_cursor_is_ahead")
