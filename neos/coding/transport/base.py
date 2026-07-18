from typing import Protocol

from neos.coding.domain.events import CodingEvent


class CodingEventSubscriptionClosed(RuntimeError):
    pass


class CodingEventSubscriptionOverloaded(CodingEventSubscriptionClosed):
    pass


class CodingTicketStore(Protocol):
    @property
    def expires_in(self) -> int: ...

    async def issue(self, *, owner_id: str, task_id: str) -> str: ...

    async def consume(self, token: str, *, task_id: str) -> str | None: ...


class CodingEventSubscription(Protocol):
    async def get(self) -> CodingEvent: ...

    async def close(self) -> None: ...


class CodingEventTransport(Protocol):
    async def publish(self, event: CodingEvent) -> None: ...

    async def subscribe(self, task_id: str) -> CodingEventSubscription: ...

    async def close(self) -> None: ...
