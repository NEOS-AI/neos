import hashlib
import json
import secrets
from typing import Any


_CONSUME_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
"""


class RedisCodingTicketStore:
    """Atomic, cross-worker WebSocket ticket store backed by Redis."""

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = 30,
        key_prefix: str = "neos:coding:ws-ticket",
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix.rstrip(":")

    @property
    def expires_in(self) -> int:
        return self._ttl_seconds

    def _key(self, token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{self._key_prefix}:{digest}"

    async def issue(self, *, owner_id: str, task_id: str) -> str:
        value = json.dumps(
            {"owner_id": owner_id, "task_id": task_id},
            separators=(",", ":"),
        )
        for _ in range(3):
            token = f"cwt_{secrets.token_urlsafe(32)}"
            created = await self._redis.set(
                self._key(token),
                value,
                ex=self._ttl_seconds,
                nx=True,
            )
            if created:
                return token
        raise RuntimeError("failed to allocate a unique coding WebSocket ticket")

    async def consume(self, token: str, *, task_id: str) -> str | None:
        raw = await self._redis.eval(_CONSUME_SCRIPT, 1, self._key(token))
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            record = json.loads(raw)
        except (UnicodeDecodeError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict) or record.get("task_id") != task_id:
            return None
        owner_id = record.get("owner_id")
        return owner_id if isinstance(owner_id, str) and owner_id else None
