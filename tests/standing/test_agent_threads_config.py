"""Q8a: the thread flag is off in the schema and on in development only
(decision Q8-6). Read by name, not by counting enabled flags."""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.config.loader import load_yaml_file
from neos.config.schema import StandingAgentsConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.mark.no_db
def test_threads_are_off_by_default() -> None:
    assert StandingAgentsConfig().threads.enabled is False


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("profile", "enabled"),
    [
        ("neos.development.yaml", True),
        ("neos.staging.yaml", False),
        ("neos.production.yaml", False),
    ],
)
def test_threads_flag_per_profile(profile: str, enabled: bool) -> None:
    data = load_yaml_file(CONFIG_DIR / profile)
    threads = (data.get("standing_agents") or {}).get("threads") or {}
    assert bool(threads.get("enabled", False)) is enabled
