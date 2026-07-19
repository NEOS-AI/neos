import importlib
import sys
from pathlib import Path

import pytest

from neos.config.schema import AppConfig
from neos.config.settings import Settings


@pytest.mark.no_db
def test_main_bootstrap_gets_settings_through_accessor():
    source = Path("neos/main.py").read_text(encoding="utf-8")

    assert "from neos.config.settings import get_settings" in source
    assert "settings = get_settings()" in source
    assert "from neos.config.settings import settings" not in source


@pytest.mark.no_db
def test_celery_app_bootstrap_uses_current_settings_singleton(monkeypatch):
    import neos.config.settings as settings_module

    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)

    configured_settings = Settings(
        config=AppConfig.model_validate(
            {
                "celery": {
                    "broker_url": "redis://broker.example:6379/4",
                    "result_backend": "redis://backend.example:6379/5",
                    "worker_prefetch_multiplier": 7,
                }
            }
        )
    )
    monkeypatch.setattr(settings_module, "get_settings", lambda: configured_settings)

    cached = sys.modules.get("neos.workflow.celery_app")
    celery_module = importlib.reload(cached) if cached is not None else importlib.import_module(
        "neos.workflow.celery_app"
    )
    configured_app = celery_module.create_celery_app(
        configured_settings, name="neos_workflow_startup_test"
    )

    assert celery_module.settings is configured_settings
    assert configured_app.conf.broker_url == "redis://broker.example:6379/4"
    assert configured_app.conf.result_backend == "redis://backend.example:6379/5"
    assert celery_module.app.conf.worker_prefetch_multiplier == 7
