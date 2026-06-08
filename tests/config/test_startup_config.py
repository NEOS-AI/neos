import importlib
import sys
from pathlib import Path

import pytest

from neos.config.schema import AppConfig
from neos.config.settings import Settings


def _drop_module(name: str) -> None:
    sys.modules.pop(name, None)


@pytest.mark.no_db
def test_main_bootstrap_gets_settings_through_accessor():
    source = Path("neos/main.py").read_text(encoding="utf-8")

    assert "from neos.config.settings import get_settings" in source
    assert "settings = get_settings()" in source
    assert "from neos.config.settings import settings" not in source


@pytest.mark.no_db
def test_celery_app_bootstrap_uses_current_settings_singleton(monkeypatch):
    import neos.config.settings as settings_module

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

    _drop_module("neos.workflow.celery_app")
    celery_module = importlib.import_module("neos.workflow.celery_app")

    assert celery_module.settings is configured_settings
    assert celery_module.app.conf.broker_url == "redis://broker.example:6379/4"
    assert celery_module.app.conf.result_backend == "redis://backend.example:6379/5"
    assert celery_module.app.conf.worker_prefetch_multiplier == 7
