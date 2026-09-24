import pytest

from neos.config.coding_selection import (
    coding_credential_for,
    resolve_coding_selection,
    resolve_coding_selection_from_app,
)
from neos.config.model_config import model_config
from neos.config.schema import AppConfig, CodingModelConfig, ModelRoutingConfig


pytestmark = pytest.mark.no_db


def test_default_anthropic_uses_everyday_role() -> None:
    selected = resolve_coding_selection(
        coding=CodingModelConfig(),
        routing=ModelRoutingConfig(),
    )

    assert selected.provider == "anthropic"
    assert selected.model == model_config.catalog.role_aliases["sonnet-5"].current
    assert selected.source == "role_default"


def test_coding_role_alias_override_resolves_to_current_pin() -> None:
    selected = resolve_coding_selection(
        coding=CodingModelConfig(model="sonnet-5"),
        routing=ModelRoutingConfig(),
    )

    assert selected.provider == "anthropic"
    assert selected.model == model_config.catalog.role_aliases["sonnet-5"].current
    assert selected.source == "catalog"


def test_openai_provider_without_model_uses_everyday_role() -> None:
    selected = resolve_coding_selection(
        coding=CodingModelConfig(provider="openai"),
        routing=ModelRoutingConfig(),
    )

    assert selected.provider == "openai"
    assert selected.model == "gpt-6-sol"
    assert selected.source == "role_default"


def test_sol_and_astra_are_both_selectable_openai_models() -> None:
    for model in ("gpt-6-sol", "gpt-6-astra"):
        selected = resolve_coding_selection(
            coding=CodingModelConfig(provider="anthropic", model=model),
            routing=ModelRoutingConfig(),
        )
        assert selected == selected
        assert selected.provider == "openai"
        assert selected.model == model


def test_unknown_model_keeps_configured_provider() -> None:
    selected = resolve_coding_selection(
        coding=CodingModelConfig(provider="openai", model="gpt-future"),
        routing=ModelRoutingConfig(),
    )

    assert selected.provider == "openai"
    assert selected.model == "gpt-future"
    assert selected.source == "feature_override"


def test_ollama_default_uses_catalog_even_when_not_selectable() -> None:
    selected = resolve_coding_selection(
        coding=CodingModelConfig(provider="ollama"),
        routing=ModelRoutingConfig(),
    )

    assert selected.provider == "ollama"
    assert selected.model == "llama3.1:8b"


def test_gemini_default_comes_from_catalog() -> None:
    selected = resolve_coding_selection(
        coding=CodingModelConfig(provider="gemini"),
        routing=ModelRoutingConfig(),
    )

    assert selected.provider == "gemini"
    assert selected.model == "gemini-2.0-flash-exp"
    assert selected.source == "provider_default"


def test_ollama_credential_is_the_configured_base_url() -> None:
    config = AppConfig.model_validate({})
    assert coding_credential_for(config, "ollama") == "http://localhost:11434"

    empty = AppConfig.model_validate(
        {"model_providers": {"ollama": {"base_url": "   "}}}
    )
    assert coding_credential_for(empty, "ollama") is None


def test_app_config_openai_astra_round_trip() -> None:
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "provider": "openai",
                "model": "gpt-6-astra",
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"openai_api_key": "sk-test"},
        }
    )

    selected = resolve_coding_selection_from_app(config)
    assert selected.provider == "openai"
    assert selected.model == "gpt-6-astra"
