"""In-process per-session lock and single-slot inbound park.

Second acquire is not a FIFO queue. CHAT/PROMPT may park one payload
(latest wins) and fold after unlock. Other busy inbound is a drop.
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class SessionInflightLock:
    def __init__(self) -> None:
        self._held: set[str] = set()

    def acquire(self, session_id: str) -> bool:
        if session_id in self._held:
            return False
        self._held.add(session_id)
        return True

    def release(self, session_id: str) -> None:
        self._held.discard(session_id)


class SessionInboundPark(Generic[T]):
    """At most one parked inbound per session. Latest put wins."""

    def __init__(self) -> None:
        self._parked: dict[str, T] = {}

    def put(self, session_id: str, payload: T) -> None:
        self._parked[session_id] = payload

    def take(self, session_id: str) -> T | None:
        return self._parked.pop(session_id, None)

    def peek(self, session_id: str) -> T | None:
        return self._parked.get(session_id)

    def clear(self, session_id: str) -> None:
        self._parked.pop(session_id, None)
