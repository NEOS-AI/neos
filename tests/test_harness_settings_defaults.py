import importlib
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.no_db


def test_direct_repair_mutation_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED", raising=False)

    import neos.config.settings as settings_module

    reloaded = importlib.reload(settings_module)

    assert reloaded.Settings().RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED is False


def test_yaml_config_keeps_direct_repair_disabled_by_default():
    config = yaml.safe_load(Path("config/neos.default.yaml").read_text(encoding="utf-8"))
    template = Path(".env.template").read_text(encoding="utf-8")

    assert config["research_harness"]["direct_repair"]["enabled"] is False
    assert "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED" not in template
