import pytest
from pydantic import ValidationError

from neos.config.model_routing import ResolutionSource, is_claude_5, resolve_model
from neos.config.schema import ModelRoutingConfig


def test_role_defaults_map_to_current_models() -> None:
    config = ModelRoutingConfig()

    assert (
        resolve_model(config=config, provider="anthropic", role="everyday").model
        == "claude-sonnet-5"
    )
    assert (
        resolve_model(config=config, provider="anthropic", role="powerful").model
        == "claude-opus-5"
    )
    assert (
        resolve_model(config=config, provider="openai", role="everyday").model
        == "gpt-5.6-terra"
    )
    assert (
        resolve_model(config=config, provider="openai", role="powerful").model
        == "gpt-5.6-sol"
    )


def test_user_selection_has_stable_highest_precedence() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="anthropic",
        role="powerful",
        user_model="claude-sonnet-4-6",
        conversation_model="claude-opus-4-8",
        feature_override="claude-opus-5",
    )

    assert result.model == "claude-sonnet-4-6"
    assert result.source is ResolutionSource.USER
    assert result.provider == "anthropic"
    assert result.role == "powerful"


def test_conversation_selection_overrides_feature_selection() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="openai",
        role="everyday",
        conversation_model="gpt-5.6-sol",
        feature_override="gpt-5.6-terra",
    )

    assert result.model == "gpt-5.6-sol"
    assert result.source is ResolutionSource.CONVERSATION


def test_feature_selection_overrides_role_default() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="openai",
        role="everyday",
        feature_override="gpt-5.6-sol",
    )

    assert result.model == "gpt-5.6-sol"
    assert result.source is ResolutionSource.FEATURE_OVERRIDE


@pytest.mark.parametrize(
    ("provider", "role"),
    [("gemini", "everyday"), ("anthropic", "fast")],
)
def test_resolver_rejects_unknown_provider_or_role(provider: str, role: str) -> None:
    with pytest.raises(ValueError, match="Unknown model (provider|role)"):
        resolve_model(  # type: ignore[arg-type]
            config=ModelRoutingConfig(),
            provider=provider,
            role=role,
        )


def test_model_routing_config_rejects_incomplete_provider_mapping() -> None:
    with pytest.raises(ValidationError):
        ModelRoutingConfig.model_validate(
            {"anthropic": {"everyday": "claude-sonnet-5"}}
        )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-sonnet-5", True),
        ("claude-opus-5", True),
        ("claude-sonnet-5-20260101", False),
        ("claude-sonnet-4-5-20250929", False),
        ("claude-sonnet-4-6", False),
        ("gpt-5.6-terra", False),
        ("claude-sonnet-50", False),
    ],
)
def test_is_claude_5_matches_only_claude_five_models(
    model: str, expected: bool
) -> None:
    assert is_claude_5(model) is expected
