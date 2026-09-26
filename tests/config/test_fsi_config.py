import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig, FsiConfig

pytestmark = pytest.mark.no_db


def test_fsi_flags_default_off() -> None:
    config = AppConfig()
    assert config.fsi.enabled is False
    assert config.fsi.mode_b_enabled is False
    assert config.fsi.mode_a_enabled is False
    assert config.fsi.partner_mcp is False


def test_fsi_mode_b_on_with_master_off_raises() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"fsi": {"enabled": False, "mode_b_enabled": True}})


def test_fsi_mode_a_on_with_master_off_raises() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"fsi": {"enabled": False, "mode_a_enabled": True}})


def test_fsi_partner_mcp_on_with_master_off_raises() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"fsi": {"enabled": False, "partner_mcp": True}})


def test_fsi_mode_b_on_with_master_on_loads() -> None:
    config = AppConfig.model_validate(
        {"fsi": {"enabled": True, "mode_b_enabled": True}}
    )
    assert config.fsi.enabled is True
    assert config.fsi.mode_b_enabled is True
    assert isinstance(config.fsi, FsiConfig)
