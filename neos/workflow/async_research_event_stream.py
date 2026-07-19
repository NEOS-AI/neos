"""Redis Streams transport for cross-process async research events."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from neos.utils.cache import cache_manager
from neos.workflow.stream_manager import StreamEvent

logger = logging.getLogger(__name__)

EVENT_ID_PATTERN = re.compile(r"^(?:0|[1-9]\d*)-(?:0|[1-9]\d*)$")


def validate_event_id(value: str) -> str:
    """Validate a Redis stream entry ID used as an SSE cursor."""
    if not EVENT_ID_PATTERN.fullmatch(value):
        raise ValueError("Invalid Redis stream event ID")
    return value


def _decode(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class AsyncResearchEventStream:
    """Append and replay async research events through a Redis Stream."""

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        key_prefix: str = "neos:async-research:events",
        ttl_seconds: int = 86400,
        max_length: int = 1000,
    ) -> None:
        self._redis = redis_client
        self.key_prefix = key_prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds
        self.max_length = max_length

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}:{session_id}"

    async def _client(self) -> Any:
        if self._redis is not None:
            return self._redis
        if cache_manager.redis_client is None:
            await cache_manager.initialize()
        if cache_manager.redis_client is None:
            raise RuntimeError("Redis client was not initialized")
        return cache_manager.redis_client

    async def append(self, session_id: str, event: str, data: Any) -> str:
        client = await self._client()
        key = self._key(session_id)
        event_id = await client.xadd(
            key,
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
            maxlen=self.max_length,
            approximate=True,
        )
        await client.expire(key, self.ttl_seconds)
        return _decode(event_id)

    async def read_after(
        self,
        session_id: str,
        last_event_id: str = "0-0",
        *,
        block_ms: int = 15000,
        count: int = 100,
    ) -> list[StreamEvent]:
        cursor = validate_event_id(last_event_id)
        records = await (await self._client()).xread(
            {self._key(session_id): cursor},
            count=count,
            block=block_ms,
        )
        events: list[StreamEvent] = []
        for _, entries in records:
            for raw_event_id, raw_fields in entries:
                event_id = _decode(raw_event_id)
                try:
                    fields = {
                        _decode(key): _decode(value)
                        for key, value in raw_fields.items()
                    }
                    event = fields["event"]
                    data = fields["data"]
                    json.loads(data)
                except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning(
                        "Skipping malformed async research event: session=%s event_id=%s",
                        session_id,
                        event_id,
                    )
                    continue
                events.append(StreamEvent(id=event_id, event=event, data=data))
        return events


async_research_event_stream = AsyncResearchEventStream()
