import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher
from neos.coding.outbox.repository import PostgresCodingOutboxRepository
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.coding.transport.base import CodingEventTransport, CodingTicketStore
from neos.coding.transport.memory import (
    InMemoryWsTicketStore,
    InProcessCodingEventBroker,
)
from neos.coding.transport.redis_events import RedisCodingEventTransport
from neos.coding.transport.redis_tickets import RedisCodingTicketStore
from neos.database.connection import db_manager


@dataclass(frozen=True, slots=True)
class CodingRuntimeTransport:
    tickets: CodingTicketStore
    events: CodingEventTransport


coding_transport = CodingRuntimeTransport(
    tickets=InMemoryWsTicketStore(),
    events=InProcessCodingEventBroker(),
)
coding_outbox_repository = PostgresCodingOutboxRepository(db_manager.get_session)
coding_outbox_dispatcher = CodingOutboxDispatcher(
    coding_outbox_repository, coding_transport.events
)
coding_service = PostgresCodingService(
    db_manager.get_session, wake_outbox=coding_outbox_dispatcher.wake
)
coding_run_service = CodingRunService(
    tasks=CodingTaskRepository(db_manager),
    runs=PostgresCodingRunRepository(db_manager.get_session),
    events=coding_service,
    interrupter=InProcessRunInterrupter(),
)


def initialize_coding_transport(
    *, redis_client: Any | None, production: bool
) -> CodingRuntimeTransport:
    global coding_transport
    if production:
        if redis_client is None:
            raise RuntimeError("Redis is required for production coding transport")
        runtime = CodingRuntimeTransport(
            tickets=RedisCodingTicketStore(redis_client),
            events=RedisCodingEventTransport(redis_client),
        )
    else:
        runtime = CodingRuntimeTransport(
            tickets=InMemoryWsTicketStore(),
            events=InProcessCodingEventBroker(),
        )
    coding_transport = runtime
    coding_outbox_dispatcher.set_publisher(runtime.events)
    return runtime


async def close_coding_transport() -> None:
    await coding_transport.events.close()


def get_coding_ticket_store() -> CodingTicketStore:
    return coding_transport.tickets


def get_coding_event_transport() -> CodingEventTransport:
    return coding_transport.events


def start_coding_outbox_dispatcher(
    dispatcher: CodingOutboxDispatcher = coding_outbox_dispatcher,
) -> asyncio.Task:
    return asyncio.create_task(
        dispatcher.run(), name="coding-outbox-dispatcher"
    )


async def stop_coding_outbox_dispatcher(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
