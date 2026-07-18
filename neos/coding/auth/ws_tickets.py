import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class WsTicket:
    owner_id: str
    task_id: str
    expires_at: datetime


class InMemoryWsTicketStore:
    """Single-process ticket store; Redis adapter will preserve this contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ttl: timedelta = timedelta(seconds=30),
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._tickets: dict[str, WsTicket] = {}
        self._lock = asyncio.Lock()

    @property
    def expires_in(self) -> int:
        return int(self._ttl.total_seconds())

    async def issue(self, *, owner_id: str, task_id: str) -> str:
        token = f"cwt_{uuid4().hex}"
        async with self._lock:
            self._tickets[token] = WsTicket(
                owner_id=owner_id,
                task_id=task_id,
                expires_at=self._clock() + self._ttl,
            )
        return token

    async def consume(self, token: str, *, task_id: str) -> str | None:
        async with self._lock:
            ticket = self._tickets.get(token)
            if ticket is None or ticket.task_id != task_id:
                return None
            self._tickets.pop(token, None)
        if ticket.expires_at <= self._clock():
            return None
        return ticket.owner_id


ws_ticket_store = InMemoryWsTicketStore()
