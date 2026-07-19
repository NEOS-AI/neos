from datetime import UTC, datetime

from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
import pytest

import neos.coding.runtime as runtime_module
from neos.coding.runtime import create_coding_runtime
from neos.config.schema import AppConfig
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


def test_development_prepares_real_loop_before_provider_allocation(monkeypatch) -> None:
    config = AppConfig.model_validate({
        "coding_model": {
            "enabled": True,
            "input_cost_micros_per_million": 1,
            "output_cost_micros_per_million": 1,
        },
        "sandbox": {"enabled": True},
        "secrets": {"anthropic_api_key": "test"},
    })
    allocations = []
    monkeypatch.setattr(runtime_module.settings, "CODING_FAKE_LOOP_ENABLED", False)
    monkeypatch.setattr(runtime_module.settings, "CODING_CELERY_ENABLED", False)
    monkeypatch.setattr(
        runtime_module,
        "_prepare_real_coding_loop",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("prepare failed")),
    )
    monkeypatch.setattr(
        runtime_module, "create_sandbox_provider", lambda config: allocations.append(config)
    )

    with pytest.raises(RuntimeError, match="prepare failed"):
        runtime_module.create_development_coding_runtime(config=config)

    assert allocations == []
