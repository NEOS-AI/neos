"""In-process per-session lock. Second acquire is a drop, not a queue."""

from __future__ import annotations


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
