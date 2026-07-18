import asyncio

from neos.coding.runtime import (
    close_coding_transport,
    initialize_coding_transport,
    start_coding_outbox_dispatcher,
    stop_coding_outbox_dispatcher,
)
from neos.coding.transport.memory import (
    InMemoryWsTicketStore,
    InProcessCodingEventBroker,
)
from neos.coding.transport.redis_events import RedisCodingEventTransport
from neos.coding.transport.redis_tickets import RedisCodingTicketStore


class BlockingDispatcher:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self) -> None:
        self.started.set()
        await asyncio.Event().wait()


async def test_start_and_stop_manage_dispatcher_task() -> None:
    dispatcher = BlockingDispatcher()
    task = start_coding_outbox_dispatcher(dispatcher)
    await dispatcher.started.wait()

    await stop_coding_outbox_dispatcher(task)

    assert task.cancelled()


def test_production_requires_redis_and_selects_redis_adapters() -> None:
    try:
        initialize_coding_transport(redis_client=None, production=True)
    except RuntimeError as error:
        assert "Redis" in str(error)
    else:
        raise AssertionError("production initialization must fail without Redis")

    redis = object()
    runtime = initialize_coding_transport(redis_client=redis, production=True)

    assert isinstance(runtime.tickets, RedisCodingTicketStore)
    assert isinstance(runtime.events, RedisCodingEventTransport)


async def test_development_explicitly_selects_in_memory_adapters() -> None:
    runtime = initialize_coding_transport(redis_client=None, production=False)

    assert isinstance(runtime.tickets, InMemoryWsTicketStore)
    assert isinstance(runtime.events, InProcessCodingEventBroker)
    await close_coding_transport()
    initialize_coding_transport(redis_client=None, production=False)
