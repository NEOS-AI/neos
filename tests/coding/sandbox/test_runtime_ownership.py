from datetime import UTC, datetime

from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.runtime import create_coding_runtime
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 10, tzinfo=UTC)


class EmptyProjectionRepository:
    async def snapshot(self, task_id: str):
        return None


class RecordingSandboxProvider:
    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


async def test_runtime_owns_injected_sandbox_provider() -> None:
    provider = RecordingSandboxProvider()
    runtime = create_coding_runtime(
        events=InMemoryCodingEventStore(),
        tasks=object(),
        run_repository=InMemoryCodingRunRepository(),
        projection_repository=EmptyProjectionRepository(),
        loop=FakeDurableCodingLoop(clock=lambda: NOW),
        sandboxes=provider,
        clock=lambda: NOW,
    )

    assert runtime.sandboxes is provider
    await runtime.close()
    await runtime.close()

    assert provider.close_count == 1
