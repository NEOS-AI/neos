"""Q9a: the ask flag is off by default and only takes effect with its two
dependencies (design §9.1). Read by name, not by counting enabled flags."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.config.schema import StandingAgentsConfig, StandingAskConfig
from neos.standing.asks import ask_effective

pytestmark = pytest.mark.no_db


def test_ask_is_off_by_default_with_a_day_to_answer() -> None:
    ask = StandingAgentsConfig().ask
    assert ask.enabled is False
    assert ask.expire_hours == 24


def test_expire_hours_must_be_positive() -> None:
    with pytest.raises(ValueError):
        StandingAskConfig(expire_hours=0)


def _config(**off):
    flags = {"enabled": True, "ask": True, "notifications": True, "threads": True}
    flags.update(off)
    standing = StandingAgentsConfig.model_validate(
        {
            "enabled": flags["enabled"],
            "ask": {"enabled": flags["ask"]},
            "notifications": {"enabled": flags["notifications"]},
            "threads": {"enabled": flags["threads"]},
        }
    )
    return SimpleNamespace(standing_agents=standing)


def test_all_four_on_is_effective() -> None:
    assert ask_effective(_config()) is True


@pytest.mark.parametrize("flag", ["enabled", "ask", "notifications", "threads"])
def test_any_one_off_is_not_effective(flag) -> None:
    """No drain -> the question never leaves; no threads -> no answer is recognised."""
    assert ask_effective(_config(**{flag: False})) is False
