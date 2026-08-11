from datetime import UTC, datetime

from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.model.anthropic import AnthropicCodingModel
from neos.dataset.adapters import TrackedCodingModel
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
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    allocations = []
    monkeypatch.setattr(runtime_module.settings, "CODING_FAKE_LOOP_ENABLED", False)
    monkeypatch.setattr(runtime_module.settings, "CODING_CELERY_ENABLED", False)
    monkeypatch.setattr(
        runtime_module,
        "_prepare_real_coding_loop",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("prepare failed")),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_sandbox_provider",
        lambda config: allocations.append(config),
    )

    with pytest.raises(RuntimeError, match="prepare failed"):
        runtime_module.create_development_coding_runtime(config=config)

    assert allocations == []


@pytest.mark.parametrize(
    ("feature_model", "expected_model"),
    [
        (None, "claude-sonnet-5"),
        ("claude-manual", "claude-manual"),
    ],
)
def test_real_loop_resolves_coding_model_at_runtime_boundary(
    monkeypatch, feature_model, expected_model
) -> None:
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "model": feature_model,
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    monkeypatch.setattr(runtime_module, "AsyncAnthropic", lambda **kwargs: object())

    finish = runtime_module._prepare_real_coding_loop(config=config)
    loop = finish(object())

    assert loop._config.model == expected_model


@pytest.mark.parametrize("failure_point", ["finish", "notifier"])
def test_development_closes_provider_once_after_allocation_failure(
    monkeypatch, failure_point
) -> None:
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    provider = RecordingSandboxProvider()
    monkeypatch.setattr(runtime_module.settings, "CODING_FAKE_LOOP_ENABLED", False)
    monkeypatch.setattr(
        runtime_module.settings, "CODING_CELERY_ENABLED", failure_point == "notifier"
    )
    monkeypatch.setattr(
        runtime_module, "create_sandbox_provider", lambda config: provider
    )
    if failure_point == "finish":
        monkeypatch.setattr(
            runtime_module,
            "_prepare_real_coding_loop",
            lambda **kwargs: lambda provider: (_ for _ in ()).throw(
                RuntimeError("finish failed")
            ),
        )
    else:
        monkeypatch.setattr(
            runtime_module,
            "validate_coding_worker_settings",
            lambda settings: (_ for _ in ()).throw(RuntimeError("notifier failed")),
        )

    with pytest.raises(RuntimeError, match=f"{failure_point} failed"):
        runtime_module.create_development_coding_runtime(config=config)

    assert provider.close_count == 1


def test_real_loop_wraps_the_production_model_for_collection(monkeypatch) -> None:
    """E-S4 회귀 가드.

    이 단언이 깨지면 코딩 루프의 LLM 호출이 데이터셋 원장에서 조용히 샌다.
    D1c(`7f4beca1`)가 계측을 전송 계층 **밖에서** 감싼 이유가 여기 있다 --
    래퍼가 벗겨져도 루프는 정상 동작하므로 테스트 없이는 아무도 모른다.
    """
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    monkeypatch.setattr(runtime_module, "AsyncAnthropic", lambda **kwargs: object())

    finish = runtime_module._prepare_real_coding_loop(config=config)
    loop = finish(object())

    assert isinstance(loop._model, TrackedCodingModel)
    assert isinstance(loop._model._inner, AnthropicCodingModel)
    assert loop._model._workflow_step == "coding_loop"
