"""설정 `model_routing.effort.models` 는 부팅 때 카탈로그와 맞대 본다."""

from __future__ import annotations

import pytest

from neos.config.model_config import effort_levels_for
from neos.config.schema import AppConfig

pytestmark = pytest.mark.no_db


def _a_model_with_levels() -> tuple[str, str]:
    for name in ("claude-opus-5-5", "gpt-6-sol"):
        levels = effort_levels_for(name)
        if levels:
            return name, levels[0]
    pytest.skip("no catalog model declares effort levels")


def test_models_default_is_empty() -> None:
    assert AppConfig().model_routing.effort.models == {}


def test_a_known_pin_and_level_is_accepted() -> None:
    name, level = _a_model_with_levels()
    config = AppConfig.model_validate(
        {"model_routing": {"effort": {"models": {name: level}}}}
    )
    assert config.model_routing.effort.models == {name: level}


def test_an_unknown_pin_stops_boot() -> None:
    with pytest.raises(ValueError, match="not a catalog model"):
        AppConfig.model_validate(
            {"model_routing": {"effort": {"models": {"claude-nope": "low"}}}}
        )


def test_a_level_the_model_does_not_take_stops_boot() -> None:
    name, _ = _a_model_with_levels()
    with pytest.raises(ValueError, match="does not take"):
        AppConfig.model_validate(
            {"model_routing": {"effort": {"models": {name: "bogus"}}}}
        )
