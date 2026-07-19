import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.application.snapshot_service import CodingSnapshotService
from neos.coding.loop.base import CodingLoop
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher
from neos.coding.outbox.repository import PostgresCodingOutboxRepository
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.repositories.projection_repository import (
    PostgresCodingProjectionRepository,
)
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.coding.transport.base import CodingEventTransport, CodingTicketStore
from neos.coding.transport.memory import (
    InMemoryWsTicketStore,
    InProcessCodingEventBroker,
)
from neos.coding.transport.redis_events import RedisCodingEventTransport
from neos.coding.transport.redis_tickets import RedisCodingTicketStore
from neos.database.connection import db_manager
from neos.config.settings import settings
from neos.observability.metrics import metrics


@dataclass(frozen=True, slots=True)
class CodingRuntimeTransport:
    tickets: CodingTicketStore
    events: CodingEventTransport


@dataclass(frozen=True, slots=True)
class CodingRuntime:
    events: Any
    runs: CodingRunService
    snapshots: CodingSnapshotService


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


def create_coding_runtime(
    *,
    events,
    tasks,
    run_repository,
    projection_repository,
    loop: CodingLoop | None,
    metrics_collector=None,
    interrupter=None,
    clock=None,
) -> CodingRuntime:
    snapshots = CodingSnapshotService(projection_repository)
    run_kwargs = {}
    if clock is not None:
        run_kwargs["clock"] = clock
    runs = CodingRunService(
        tasks=tasks,
        runs=run_repository,
        events=events,
        loop=loop,
        metrics=metrics_collector,
        interrupter=interrupter or InProcessRunInterrupter(),
        **run_kwargs,
    )
    return CodingRuntime(events=events, runs=runs, snapshots=snapshots)


def create_development_coding_runtime() -> CodingRuntime:
    loop = (
        FakeDurableCodingLoop(clock=lambda: datetime.now(UTC))
        if settings.CODING_FAKE_LOOP_ENABLED
        else None
    )
    return create_coding_runtime(
        events=coding_service,
        tasks=CodingTaskRepository(db_manager),
        run_repository=PostgresCodingRunRepository(db_manager.get_session),
        projection_repository=PostgresCodingProjectionRepository(
            db_manager.get_session
        ),
        loop=loop,
        metrics_collector=metrics,
        interrupter=InProcessRunInterrupter(),
    )


coding_runtime = create_development_coding_runtime()
coding_run_service = coding_runtime.runs
coding_snapshot_service = coding_runtime.snapshots


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
