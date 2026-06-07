import importlib
from pathlib import Path


def test_direct_repair_mutation_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED", raising=False)

    import neos.config.settings as settings_module

    reloaded = importlib.reload(settings_module)

    assert reloaded.Settings().RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED is False


def test_env_template_keeps_direct_repair_disabled_by_default():
    template = Path(".env.template").read_text(encoding="utf-8")

    assert "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED=false" in template
