"""24h idempotent /new generation fence. Separate from inbound claim TTL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

GENERATION_FENCE_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class ChannelGenerationFence:
    session_id: str
    generation_id: str
    created_at: datetime


class InMemoryChannelGenerationFenceStore:
    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._items: dict[tuple[str, str], ChannelGenerationFence] = {}
        self._clock = clock

    def _drop_expired(self, key: tuple[str, str]) -> None:
        existing = self._items.get(key)
        if existing is None:
            return
        if self._clock() - existing.created_at > GENERATION_FENCE_TTL:
            self._items.pop(key, None)

    async def claim(
        self, session_id: str, generation_id: str
    ) -> tuple[bool, ChannelGenerationFence | None]:
        key = (session_id, generation_id)
        self._drop_expired(key)
        existing = self._items.get(key)
        if existing is not None:
            return False, existing
        record = ChannelGenerationFence(
            session_id=session_id,
            generation_id=generation_id,
            created_at=self._clock(),
        )
        self._items[key] = record
        return True, record

    async def get(
        self, session_id: str, generation_id: str
    ) -> ChannelGenerationFence | None:
        key = (session_id, generation_id)
        self._drop_expired(key)
        return self._items.get(key)
