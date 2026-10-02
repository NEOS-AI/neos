"""Q5b MP7: the resume route is there whenever something can pause a task.

Q10b mounted `POST /coding/tasks/{id}/resume` only with `standing_agents.enabled`
-- the envelope was the only thing that paused. The monitor pauses any task, so
with monitor enforcement on and standing agents off a paused task would have no
way back. One predicate decides; `neos/main.py` uses it outside the standing block.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from neos.api.handlers.standing_pause_handlers import resume_route_mounted
from neos.config.schema import AppConfig

pytestmark = pytest.mark.no_db

RESUME = ("POST", "/api/v1/coding/tasks/{task_id}/resume")
ROOT = Path(__file__).resolve().parents[2]

ENFORCING_JEV = {
    "enabled": True,
    "model": "jev-1.13.0",
    "monitor": {
        "shadow_enabled": True,
        "enforce": True,
        "pause_at_or_above": 0.8,
        "user_only": 1,
        "mode_ceiling": 2,
        "denial_window": 10,
        "denials_in_window": 3,
        "repeated_call": 3,
        "refusals": 1,
        "spend_multiple": 4.0,
        "spend_warmup_turns": 5,
    },
}


def test_nothing_can_pause_so_there_is_no_route() -> None:
    assert resume_route_mounted(AppConfig()) is False


def test_the_envelope_can_pause() -> None:
    assert resume_route_mounted(AppConfig(standing_agents={"enabled": True})) is True


def test_the_enforcing_monitor_can_pause_without_standing_agents() -> None:
    config = AppConfig(jev=ENFORCING_JEV)

    assert config.standing_agents.enabled is False
    assert resume_route_mounted(config) is True


def test_a_shadow_monitor_cannot_pause() -> None:
    shadow = {**ENFORCING_JEV, "monitor": {"shadow_enabled": True, "pause_at_or_above": 0.8}}

    assert resume_route_mounted(AppConfig(jev=shadow)) is False


def test_main_mounts_the_route_by_the_predicate_outside_the_standing_block() -> None:
    source = (ROOT / "neos/main.py").read_text()

    assert "\nif resume_route_mounted(settings.config):\n" in source
    standing_block = source.split("\nif settings.config.standing_agents.enabled:\n", 1)[1]
    standing_block = standing_block.split("\nif resume_route_mounted", 1)[0]
    assert "standing_resume_router" not in standing_block


@pytest.mark.slow
def test_the_app_serves_the_route_with_only_the_monitor_enforcing(tmp_path) -> None:
    """The real app, booted with monitor enforcement on and standing agents off."""
    config = tmp_path / "enforce.yaml"
    monitor = "\n".join(f"    {k}: {v}" for k, v in ENFORCING_JEV["monitor"].items())
    config.write_text(
        "jev:\n  enabled: true\n  model: jev-1.13.0\n  monitor:\n"
        + monitor.replace("True", "true")
        + "\n"
    )
    probe = textwrap.dedent(
        """
        from tests.api.test_retired_routes import _routes
        served = _routes()
        print("RESUME", ("POST", "/api/v1/coding/tasks/{task_id}/resume") in served)
        print("NEIGHBOUR", ("POST", "/api/v1/coding/tasks") in served)
        print("STANDING", any("/standing-agents" in path for _m, path in served))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env={**os.environ, "NEOS_CONFIG_PATH": str(config)},
        capture_output=True,
        text=True,
        timeout=240,
    )

    lines = set(result.stdout.splitlines())
    assert {"RESUME True", "NEIGHBOUR True", "STANDING False"} <= lines, result.stderr[-2000:]
