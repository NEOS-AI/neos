import asyncio

from neos.coding.runtime import (
    start_coding_outbox_dispatcher,
    stop_coding_outbox_dispatcher,
)


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
