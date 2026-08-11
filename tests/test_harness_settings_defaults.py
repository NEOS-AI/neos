from pathlib import Path

import pytest
import yaml

from neos.config.settings import Settings


pytestmark = pytest.mark.no_db


def test_direct_repair_mutation_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED", raising=False)

    # Settings.__init__ loads config and env at construction time, so a fresh
    # instance already reflects the deleted env var.
    #
    # Do NOT importlib.reload(neos.config.settings) here: that re-executes the
    # module and builds a brand-new `settings` singleton, while every module
    # that already did `from neos.config.settings import settings` keeps the old
    # one. The two then disagree, and tests that patch settings to drive
    # production code (e.g. deep_analysis confidence caps) silently read stale
    # values.
    assert Settings().RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED is False


def test_yaml_config_keeps_direct_repair_disabled_by_default():
    config = yaml.safe_load(Path("config/neos.default.yaml").read_text(encoding="utf-8"))
    template = Path(".env.template").read_text(encoding="utf-8")

    assert config["research_harness"]["direct_repair"]["enabled"] is False
    assert "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED" not in template
