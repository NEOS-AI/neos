import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Mapping

from neos.coding.domain.events import CodingEvent, make_event


class InMemoryCodingEventStore:
    """Deterministic Phase 0 store used by tests and the local fake runtime."""

    def __init__(self) -> None:
        self._events: dict[str, list[CodingEvent]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def append(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
        event_id: str | None = None,
        run_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> CodingEvent:
        async with self._lock:
            event = make_event(
                task_id=task_id,
                seq=len(self._events[task_id]) + 1,
                event_type=event_type,
                payload=payload,
                now=now,
                event_id=event_id,
                run_id=run_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
            )
            self._events[task_id].append(event)
            return event

    async def append_event(self, event: CodingEvent) -> CodingEvent:
        async with self._lock:
            expected_seq = len(self._events[event.task_id]) + 1
            if event.seq != expected_seq:
                raise ValueError(
                    f"expected event seq {expected_seq}, received {event.seq}"
                )
            self._events[event.task_id].append(event)
            return event

    async def list_after(
        self, task_id: str, *, after_seq: int = 0, limit: int = 500
    ) -> list[CodingEvent]:
        if after_seq < 0:
            raise ValueError("after_seq cannot be negative")
        if limit < 1:
            raise ValueError("limit must be positive")
        return [
            event for event in self._events[task_id] if event.seq > after_seq
        ][:limit]

    async def head_seq(self, task_id: str) -> int:
        return len(self._events[task_id])
