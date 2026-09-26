import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig, UniverConfig

pytestmark = pytest.mark.no_db


def test_univer_flags_default_off() -> None:
    config = AppConfig()
    assert config.univer.enabled is False
    assert config.univer.sheets_enabled is False
    assert config.univer.docs_enabled is False
    assert config.univer.formula_enabled is False


def test_univer_sheets_on_with_master_off_raises() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"univer": {"enabled": False, "sheets_enabled": True}})


def test_univer_docs_on_with_master_off_raises() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"univer": {"enabled": False, "docs_enabled": True}})


def test_univer_formula_on_with_master_off_raises() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"univer": {"enabled": False, "formula_enabled": True}})


def test_univer_formula_requires_sheets() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"univer": {"enabled": True, "formula_enabled": True, "sheets_enabled": False}}
        )


def test_univer_sheets_on_with_master_on_loads() -> None:
    config = AppConfig.model_validate(
        {"univer": {"enabled": True, "sheets_enabled": True}}
    )
    assert config.univer.enabled is True
    assert config.univer.sheets_enabled is True
    assert isinstance(config.univer, UniverConfig)


def test_univer_formula_on_with_sheets_and_master_loads() -> None:
    config = AppConfig.model_validate(
        {
            "univer": {
                "enabled": True,
                "sheets_enabled": True,
                "formula_enabled": True,
            }
        }
    )
    assert config.univer.formula_enabled is True
