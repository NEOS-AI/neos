from typing import get_args

import pytest
from pydantic import ValidationError

from neos.config.model_config import model_config
from neos.config.model_routing import (
    ResolutionSource,
    WorkloadRole,
    resolve_model,
)
from neos.config.schema import ModelRoutingConfig, ProviderModelRolesConfig
from neos.utils.llm_factory import get_recommended_models

pytestmark = pytest.mark.no_db


def test_role_defaults_map_to_current_models() -> None:
    """Everyday/powerful are role aliases; the pin lives in role_aliases.*.current."""
    config = ModelRoutingConfig()
    catalog = model_config.catalog

    assert config.anthropic.everyday == "sonnet-5"
    assert config.anthropic.powerful == "opus-5.5"

    everyday = resolve_model(config=config, provider="anthropic", role="everyday")
    assert everyday.model == catalog.role_aliases["sonnet-5"].current
    assert everyday.role_alias == "sonnet-5"
    assert everyday.source is ResolutionSource.ROLE_DEFAULT

    powerful = resolve_model(config=config, provider="anthropic", role="powerful")
    assert powerful.model == catalog.role_aliases["opus-5.5"].current
    assert powerful.role_alias == "opus-5.5"
    assert powerful.source is ResolutionSource.ROLE_DEFAULT

    assert (
        resolve_model(config=config, provider="openai", role="everyday").model
        == "gpt-6-sol"
    )
    assert (
        resolve_model(config=config, provider="openai", role="powerful").model
        == "gpt-6-sol"
    )


def test_dated_env_yaml_overrides_still_resolve() -> None:
    config = ModelRoutingConfig.model_validate(
        {
            "anthropic": {
                "everyday": "claude-sonnet-5",
                "powerful": "claude-opus-5-5",
            },
            "openai": {
                "everyday": "gpt-6-sol",
                "powerful": "gpt-6-sol",
            },
        }
    )

    result = resolve_model(config=config, provider="anthropic", role="everyday")
    assert result.model == "claude-sonnet-5"
    assert result.role_alias == "sonnet-5"
    assert result.source is ResolutionSource.ROLE_DEFAULT


def test_unknown_role_default_is_not_replaced_with_a_hardcoded_pin() -> None:
    config = ModelRoutingConfig.model_validate(
        {
            "anthropic": {"everyday": "sonnet-9", "powerful": "opus-5.5"},
            "openai": {"everyday": "gpt-6-sol", "powerful": "gpt-6-sol"},
        }
    )

    result = resolve_model(config=config, provider="anthropic", role="everyday")
    assert result.model == "sonnet-9"
    assert result.role_alias is None


def test_user_source_applies_remaps() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="anthropic",
        role="everyday",
        user_model="anthropic/claude-opus-4.5",
    )

    assert result.model == "claude-opus-5-5"
    assert result.source is ResolutionSource.USER
    assert result.role_alias == "opus-5.5"


def test_conversation_and_feature_sources_do_not_apply_remaps() -> None:
    conversation = resolve_model(
        config=ModelRoutingConfig(),
        provider="anthropic",
        role="everyday",
        conversation_model="anthropic/claude-opus-4.5",
    )
    assert conversation.model == "anthropic/claude-opus-4.5"
    assert conversation.source is ResolutionSource.CONVERSATION
    assert conversation.role_alias is None

    feature = resolve_model(
        config=ModelRoutingConfig(),
        provider="anthropic",
        role="everyday",
        feature_override="anthropic/claude-opus-4.5",
    )
    assert feature.model == "anthropic/claude-opus-4.5"
    assert feature.source is ResolutionSource.FEATURE_OVERRIDE
    assert feature.role_alias is None


def test_user_selection_has_stable_highest_precedence() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="anthropic",
        role="powerful",
        user_model="claude-sonnet-4-6",
        conversation_model="claude-opus-4-8",
        feature_override="claude-opus-5-5",
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
        conversation_model="gpt-6-sol",
        feature_override="gpt-6-sol",
    )

    assert result.model == "gpt-6-sol"
    assert result.source is ResolutionSource.CONVERSATION


def test_feature_selection_overrides_role_default() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="openai",
        role="everyday",
        feature_override="gpt-6-sol",
    )

    assert result.model == "gpt-6-sol"
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


def test_policy_stays_at_two_roles() -> None:
    """`fast`는 의도적으로 역할이 아니다 (I6).

    저비용 워크로드(atomizer, 분류기 등)는 각자의 Haiku 설정을 유지한다.
    `fast` 역할을 도입하려면 별도 Haiku 정책 설계가 선행돼야 한다.
    """
    assert get_args(WorkloadRole) == ("everyday", "powerful")
    assert set(ProviderModelRolesConfig.model_fields) == {"everyday", "powerful"}


def test_recommendation_tiers_are_not_routing_roles() -> None:
    """get_recommended_models의 `fast` 티어는 라우팅 정책 밖의 수동 참고값이다."""
    anthropic = get_recommended_models("anthropic")

    assert set(anthropic) == {"fast", "balanced", "powerful"}
    assert anthropic["fast"] not in set(ModelRoutingConfig().anthropic.model_dump().values())


def test_substitution_applies_to_every_source() -> None:
    config = ModelRoutingConfig(substitutions={"claude-fable-5-1": "claude-opus-5-5"})
    for kwargs, source in (
        ({"user_model": "claude-fable-5-1"}, ResolutionSource.USER),
        ({"conversation_model": "claude-fable-5-1"}, ResolutionSource.CONVERSATION),
        ({"feature_override": "claude-fable-5-1"}, ResolutionSource.FEATURE_OVERRIDE),
    ):
        resolved = resolve_model(
            config=config, provider="anthropic", role="powerful", **kwargs
        )
        assert resolved.model == "claude-opus-5-5", source
        assert resolved.substituted_from == "claude-fable-5-1"
        assert resolved.source is source

    roles = ModelRoutingConfig(
        anthropic=ProviderModelRolesConfig(
            everyday="sonnet-5", powerful="claude-fable-5-1"
        ),
        substitutions={"claude-fable-5-1": "claude-opus-5-5"},
    )
    resolved = resolve_model(config=roles, provider="anthropic", role="powerful")
    assert resolved.model == "claude-opus-5-5"
    assert resolved.substituted_from == "claude-fable-5-1"


def test_unsubstituted_pick_is_untouched() -> None:
    config = ModelRoutingConfig(substitutions={"claude-fable-5-1": "claude-opus-5-5"})
    resolved = resolve_model(
        config=config, provider="anthropic", role="powerful", user_model="claude-sonnet-5"
    )
    assert resolved.model == "claude-sonnet-5"
    assert resolved.substituted_from is None


@pytest.mark.parametrize("env", ["development", "staging", "production"])
def test_shipped_config_holds_fable_back(env: str) -> None:
    """2026-10-07: Opus 5.5 is cheaper and benchmarks ahead -- Fable stays parked."""
    from neos.config.loader import DEFAULT_CONFIG_DIR, deep_merge, load_yaml_file

    data = deep_merge(
        load_yaml_file(DEFAULT_CONFIG_DIR / "neos.default.yaml"),
        load_yaml_file(DEFAULT_CONFIG_DIR / f"neos.{env}.yaml"),
    )
    config = ModelRoutingConfig.model_validate(data["model_routing"])
    resolved = resolve_model(
        config=config,
        provider="anthropic",
        role="powerful",
        feature_override="claude-fable-5-1",
    )
    assert resolved.model == "claude-opus-5-5"


@pytest.mark.parametrize(
    "substitutions, message",
    [
        ({"claude-fable-5-1": "claude-nope"}, "not a catalog model"),
        (
            {"claude-fable-5-1": "claude-opus-5-5", "claude-opus-5-5": "claude-sonnet-5"},
            "chains",
        ),
        ({"claude-fable-5-1": "gpt-6-sol"}, "different providers"),
    ],
)
def test_bad_substitutions_fail_at_boot(substitutions, message) -> None:
    from neos.config.schema import AppConfig

    with pytest.raises(ValidationError, match=message):
        AppConfig.model_validate({"model_routing": {"substitutions": substitutions}})


def test_substitution_is_counted() -> None:
    from neos.observability.metrics import get_metrics_collector

    counter = get_metrics_collector().model_substitution_total.labels(
        from_model="claude-fable-5-1", to_model="claude-opus-5-5", source="feature_override"
    )
    before = counter._value.get()
    config = ModelRoutingConfig(substitutions={"claude-fable-5-1": "claude-opus-5-5"})

    resolve_model(
        config=config, provider="anthropic", role="powerful",
        feature_override="claude-fable-5-1",
    )
    assert counter._value.get() == before + 1

    resolve_model(
        config=config, provider="anthropic", role="powerful",
        feature_override="claude-sonnet-5",
    )
    assert counter._value.get() == before + 1
