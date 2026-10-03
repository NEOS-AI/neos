"""Q5b MP2: enforcement refuses to start without an explicitly written pause boundary.

The fallback defaults are the shadow's first values (§6.1), not a measured pause
boundary, and `pause_at_or_above` has no default at all. So `enforce` needs the
monitor on, and every boundary field written in config -- a default is never the
line a task is stopped at. Off is the default.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from neos.config.schema import MONITOR_PAUSE_BOUNDARY_FIELDS, JevConfig, JevMonitorConfig
from neos.jev.assembly import MisconfiguredJev, build_trajectory_monitor

pytestmark = pytest.mark.no_db

BOUNDARY = {
    "pause_at_or_above": 0.8,
    "user_only": 1,
    "mode_ceiling": 2,
    "denial_window": 10,
    "denials_in_window": 3,
    "repeated_call": 3,
    "refusals": 1,
    "spend_multiple": 4.0,
    "spend_warmup_turns": 5,
}


def _config(**monitor):
    return JevConfig(enabled=True, model="jev-1.13.0", monitor=monitor)


def test_enforcement_is_off_by_default() -> None:
    assert JevMonitorConfig().enforce is False
    from neos.config.schema import AppConfig

    assert AppConfig().jev.monitor.enforce is False


def test_the_boundary_list_is_jevs_line_and_every_fallback_threshold() -> None:
    assert set(BOUNDARY) == set(MONITOR_PAUSE_BOUNDARY_FIELDS)


def test_enforcement_needs_the_monitor_on() -> None:
    with pytest.raises(ValidationError, match="shadow_enabled"):
        _config(enforce=True, **BOUNDARY)


@pytest.mark.parametrize("left_out", sorted(BOUNDARY))
def test_enforcement_refuses_a_boundary_left_to_its_default(left_out) -> None:
    written = {k: v for k, v in BOUNDARY.items() if k != left_out}

    with pytest.raises(ValidationError, match=left_out):
        _config(shadow_enabled=True, enforce=True, **written)


def test_the_shadow_still_runs_on_defaults() -> None:
    """Only enforcement asks for the whole boundary -- the Q5 shadow is unchanged."""
    assert _config(shadow_enabled=True, pause_at_or_above=0.8).monitor.enforce is False


def test_enforcement_cannot_loosen_a_fallback_threshold() -> None:
    """Writing the boundary does not lift §6.1's one direction: stricter only."""
    with pytest.raises(ValidationError):
        _config(shadow_enabled=True, enforce=True, **{**BOUNDARY, "repeated_call": 4})


def test_a_fully_written_boundary_builds_an_enforcing_monitor() -> None:
    config = _config(shadow_enabled=True, enforce=True, **{**BOUNDARY, "denials_in_window": 2})

    built = build_trajectory_monitor(config, api_key="k", client=object())

    assert built.enforce is True
    assert built._pause_at == 0.8
    assert built._limits.denials_in_window == 2


def test_the_factory_refuses_an_unvalidated_enforcing_config() -> None:
    """Guard before capability: a config built around validation is stopped at assembly."""
    monitor = JevMonitorConfig.model_construct(
        shadow_enabled=True, enforce=True, pause_at_or_above=0.8
    )
    config = JevConfig.model_construct(
        enabled=True, model="jev-1.13.0", monitor=monitor, timeout_sec=5.0
    )

    with pytest.raises(MisconfiguredJev, match="user_only"):
        build_trajectory_monitor(config, api_key="k", client=object())


def test_a_shadow_monitor_does_not_enforce() -> None:
    config = _config(shadow_enabled=True, pause_at_or_above=0.8)

    assert build_trajectory_monitor(config, api_key="k", client=object()).enforce is False
