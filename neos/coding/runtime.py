import asyncio
from contextlib import suppress

from neos.coding.events.broker import coding_event_broker
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher
from neos.coding.outbox.repository import PostgresCodingOutboxRepository
from neos.coding.persistence.postgres import PostgresCodingService
from neos.database.connection import db_manager


coding_service = PostgresCodingService(
    db_manager.get_session, broker=coding_event_broker
)
coding_outbox_repository = PostgresCodingOutboxRepository(db_manager.get_session)
coding_outbox_dispatcher = CodingOutboxDispatcher(
    coding_outbox_repository, coding_event_broker
)


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
