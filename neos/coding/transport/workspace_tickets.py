import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Protocol
from uuid import uuid4


class WorkspaceStreamKind(StrEnum):
    WATCHER = "watcher"
    PTY = "pty"


class WorkspaceTicketStore(Protocol):
    @property
    def expires_in(self) -> int: ...

    async def issue(
        self,
        *,
        owner_id: str,
        task_id: str,
        kind: WorkspaceStreamKind,
    ) -> str: ...

    async def consume(
        self,
        token: str,
        *,
        task_id: str,
        kind: WorkspaceStreamKind,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class WorkspaceTicket:
    owner_id: str
    task_id: str
    kind: WorkspaceStreamKind
    expires_at: datetime


class InMemoryWorkspaceTicketStore:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ttl: timedelta = timedelta(seconds=30),
    ) -> None:
        if ttl.total_seconds() <= 0:
            raise ValueError("ttl must be positive")
        self._clock = clock
        self._ttl = ttl
        self._tickets: dict[str, WorkspaceTicket] = {}
        self._lock = asyncio.Lock()

    @property
    def expires_in(self) -> int:
        return int(self._ttl.total_seconds())

    async def issue(
        self,
        *,
        owner_id: str,
        task_id: str,
        kind: WorkspaceStreamKind,
    ) -> str:
        token = f"wwt_{uuid4().hex}"
        async with self._lock:
            now = self._clock()
            self._sweep(now)
            self._tickets[token] = WorkspaceTicket(
                owner_id=owner_id,
                task_id=task_id,
                kind=kind,
                expires_at=now + self._ttl,
            )
        return token

    async def consume(
        self,
        token: str,
        *,
        task_id: str,
        kind: WorkspaceStreamKind,
    ) -> str | None:
        async with self._lock:
            now = self._clock()
            self._sweep(now)
            ticket = self._tickets.get(token)
            if (
                ticket is None
                or ticket.task_id != task_id
                or ticket.kind is not kind
            ):
                return None
            self._tickets.pop(token, None)
            return ticket.owner_id

    def _sweep(self, now: datetime) -> None:
        for token in tuple(self._tickets):
            if self._tickets[token].expires_at <= now:
                self._tickets.pop(token, None)


_CONSUME_IF_MATCHES = """
local value = redis.call('GET', KEYS[1])
if not value then return nil end
local record = cjson.decode(value)
if record['task_id'] ~= ARGV[1] or record['kind'] ~= ARGV[2] then
  return nil
end
redis.call('DEL', KEYS[1])
return value
"""


class RedisWorkspaceTicketStore:
    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = 30,
        key_prefix: str = "neos:coding:workspace-ticket",
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
        digest = hashlib.sha256(token.encode()).hexdigest()
        return f"{self._key_prefix}:{digest}"

    async def issue(
        self,
        *,
        owner_id: str,
        task_id: str,
        kind: WorkspaceStreamKind,
    ) -> str:
        value = json.dumps(
            {"owner_id": owner_id, "task_id": task_id, "kind": kind.value},
            separators=(",", ":"),
        )
        for _ in range(3):
            token = f"wwt_{secrets.token_urlsafe(32)}"
            if await self._redis.set(
                self._key(token),
                value,
                ex=self._ttl_seconds,
                nx=True,
            ):
                return token
        raise RuntimeError("workspace_ticket_allocation_failed")

    async def consume(
        self,
        token: str,
        *,
        task_id: str,
        kind: WorkspaceStreamKind,
    ) -> str | None:
        raw = await self._redis.eval(
            _CONSUME_IF_MATCHES,
            1,
            self._key(token),
            task_id,
            kind.value,
        )
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode()
            record = json.loads(raw)
        except (UnicodeDecodeError, TypeError, json.JSONDecodeError):
            return None
        owner_id = record.get("owner_id") if isinstance(record, dict) else None
        return owner_id if isinstance(owner_id, str) and owner_id else None
