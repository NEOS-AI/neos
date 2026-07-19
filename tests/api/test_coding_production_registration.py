from pathlib import Path
from types import SimpleNamespace

import pytest

import neos.coding.runtime as runtime_module
from neos.coding.runtime import coding_runtime, create_development_coding_runtime
from neos.coding.workers.celery_runtime import validate_coding_worker_settings
from neos.coding.workers.development_supervisor import (
    CodingDevelopmentSupervisor,
)
from neos.coding.workers.dispatcher import CodingDispatchSource
from neos.config.settings import settings
from neos.config.schema import AppConfig


def test_coding_websocket_bypasses_generic_production_filter() -> None:
    source = Path("neos/main.py").read_text()

    assert "app.include_router(\n    coding_ws_router" in source
    assert "_include_router_for_runtime(coding_ws_router" not in source


def test_runtime_creates_supervisor_only_with_fake_loop_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "CODING_CELERY_ENABLED", False)
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", True)
    runtime = create_development_coding_runtime()
    assert isinstance(runtime.supervisor, CodingDevelopmentSupervisor)

    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", False)
    runtime = create_development_coding_runtime()
    assert runtime.supervisor is None


def test_production_registration_does_not_create_development_supervisor() -> None:
    assert coding_runtime.supervisor is None


def test_runtime_registers_celery_dispatcher_when_enabled(
    monkeypatch,
) -> None:
    calls = []

    class RecordingDispatcher:
        def enqueue(self, task_id, *, source):
            calls.append((task_id, source))
            return "delivery-1"

    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", False)
    monkeypatch.setattr(settings, "CODING_CELERY_ENABLED", True)
    monkeypatch.setattr(
        runtime_module,
        "create_celery_dispatcher",
        lambda: RecordingDispatcher(),
    )

    runtime = create_development_coding_runtime()
    notifier = runtime_module.coding_service._task_created_notifier
    notifier("ct_1")

    assert runtime.supervisor is None
    assert calls == [("ct_1", CodingDispatchSource.API)]


def test_runtime_rejects_local_and_celery_execution_together(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", True)
    monkeypatch.setattr(settings, "CODING_CELERY_ENABLED", True)

    with pytest.raises(RuntimeError, match="cannot be enabled together"):
        create_development_coding_runtime()


def test_runtime_rejects_fake_and_real_execution_together(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", True)
    config = AppConfig.model_validate({
        "coding_model": {"enabled": True, "model": "claude-test"},
        "sandbox": {"enabled": True},
        "secrets": {"anthropic_api_key": "test-key"},
    })

    with pytest.raises(RuntimeError, match="cannot be enabled together"):
        create_development_coding_runtime(config=config)


def test_real_loop_can_register_celery_delivery(monkeypatch) -> None:
    calls = []
    config = AppConfig.model_validate({
        "coding_model": {"enabled": True, "model": "claude-test"},
        "sandbox": {"enabled": True},
        "secrets": {"anthropic_api_key": "test-key"},
    })
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", False)
    monkeypatch.setattr(settings, "CODING_CELERY_ENABLED", True)
    monkeypatch.setattr(runtime_module, "_create_real_coding_loop", lambda **kwargs: object())
    monkeypatch.setattr(
        runtime_module,
        "create_celery_dispatcher",
        lambda: SimpleNamespace(enqueue=lambda task_id, *, source: calls.append(task_id)),
    )

    runtime = create_development_coding_runtime(config=config)
    runtime_module.coding_service._task_created_notifier("ct_real")

    assert runtime.supervisor is None
    assert calls == ["ct_real"]


@pytest.mark.parametrize(
    "override",
    [
        {"CODING_CELERY_RECONCILIATION_SECONDS": 0},
        {"CODING_CELERY_DISCOVERY_BATCH_SIZE": 0},
        {"CODING_EXECUTION_LEASE_SECONDS": 0},
        {"CODING_CELERY_SOFT_TIME_LIMIT_SECONDS": 10,
         "CODING_CELERY_HARD_TIME_LIMIT_SECONDS": 10},
    ],
)
def test_invalid_coding_worker_settings_fail_startup(override) -> None:
    values = {
        "CODING_CELERY_QUEUE": "coding",
        "CODING_CELERY_RECONCILIATION_SECONDS": 10,
        "CODING_CELERY_DISCOVERY_BATCH_SIZE": 100,
        "CODING_CELERY_SOFT_TIME_LIMIT_SECONDS": 300,
        "CODING_CELERY_HARD_TIME_LIMIT_SECONDS": 360,
        "CODING_EXECUTION_LEASE_SECONDS": 30,
        **override,
    }

    with pytest.raises(ValueError):
        validate_coding_worker_settings(SimpleNamespace(**values))
