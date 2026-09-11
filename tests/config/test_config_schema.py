import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", False])
def test_string_false_values_parse_for_boolean_fields(raw):
    config = AppConfig.model_validate(
        {
            "api": {"debug": raw},
            "research_harness": {"direct_repair": {"enabled": raw}},
            "tool_search": {"enabled": raw},
        }
    )

    assert config.api.debug is False
    assert config.research_harness.direct_repair.enabled is False
    assert config.tool_search.enabled is False


@pytest.mark.parametrize("raw", ["true", "1", "yes", "on", True])
def test_string_true_values_parse_for_boolean_fields(raw):
    config = AppConfig.model_validate(
        {
            "api": {"debug": raw},
            "research_harness": {"direct_repair": {"enabled": raw}},
            "tool_search": {"enabled": raw},
        }
    )

    assert config.api.debug is True
    assert config.research_harness.direct_repair.enabled is True
    assert config.tool_search.enabled is True


def test_channel_gate_defaults_are_fail_closed():
    config = AppConfig()

    assert config.channels.require_mention is True
    assert config.channels.allowed_users == []
    assert config.channels.allowed_channels == []
    assert config.channels.ignored_channels == []
    assert config.channels.slack.require_mention is None
    assert config.channels.discord.allowed_users == []
    assert config.channels.telegram.ignored_channels == []


def test_schema_defaults_match_current_runtime_policy():
    config = AppConfig()

    assert config.environment == "development"
    assert config.api.debug is False
    assert config.api.v1_prefix == "/api/v1"
    assert config.research_harness.direct_repair.enabled is False
    assert config.model_routing.anthropic.everyday == "claude-sonnet-5"
    assert config.model_routing.anthropic.powerful == "claude-opus-5"
    assert config.model_routing.openai.everyday == "gpt-5.6-terra"
    assert config.model_routing.openai.powerful == "gpt-5.6-sol"


def test_thinking_engine_config_defaults_are_conservative():
    config = AppConfig()

    assert config.thinking_engine.enabled is True
    assert config.thinking_engine.persist_traces is False
    assert config.thinking_engine.persist_task_dag is False
    assert config.thinking_engine.task_level_harness is True


@pytest.mark.parametrize("mode", ["auto", "advisory", "gate", "off"])
def test_research_harness_default_mode_accepts_rollout_modes(mode):
    config = AppConfig.model_validate({"research_harness": {"default_mode": mode}})

    assert config.research_harness.default_mode == mode


def test_research_harness_default_mode_rejects_unknown_value():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"research_harness": {"default_mode": "enforced"}})


def test_research_harness_persistence_policies_are_constrained():
    config = AppConfig.model_validate(
        {
            "research_harness": {
                "persistence": {
                    "evidence_storage_policy": "redacted",
                    "cache_policy": "allow_advisory_fail",
                }
            }
        }
    )

    assert config.research_harness.persistence.evidence_storage_policy == "redacted"
    assert config.research_harness.persistence.cache_policy == "allow_advisory_fail"

    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"research_harness": {"persistence": {"evidence_storage_policy": "everything"}}}
        )

    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"research_harness": {"persistence": {"cache_policy": "cache_all_failures"}}}
        )


def test_default_autonomy_level_is_constrained():
    for level in (0, 1, 2):
        config = AppConfig.model_validate({"execution_approval": {"default_autonomy_level": level}})
        assert config.execution_approval.default_autonomy_level == level

    with pytest.raises(ValidationError):
        AppConfig.model_validate({"execution_approval": {"default_autonomy_level": 3}})


@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_anthropic_feature_config_accepts_supported_cache_ttls(ttl):
    config = AppConfig.model_validate(
        {
            "llm": {
                "prompt_caching": {"ttl": ttl},
                "advisor": {"prompt_caching": {"ttl": ttl}},
            }
        }
    )

    assert config.llm.prompt_caching.ttl == ttl
    assert config.llm.advisor.prompt_caching.ttl == ttl


def test_anthropic_feature_config_defaults():
    config = AppConfig()

    assert config.llm.prompt_caching.enabled is True
    assert config.llm.prompt_caching.ttl == "5m"
    assert config.llm.advisor.enabled is False
    assert config.llm.advisor.model == "claude-opus-4-8"
    assert config.llm.advisor.max_uses == 2
    assert config.llm.advisor.max_tokens == 2048
    assert config.llm.advisor.max_pause_turns == 3
    assert config.llm.advisor.prompt_caching.enabled is False


@pytest.mark.parametrize(
    "advisor",
    [
        {"max_uses": 0},
        {"max_tokens": 1023},
        {"max_pause_turns": -1},
        {"prompt_caching": {"ttl": "30m"}},
    ],
)
def test_anthropic_feature_config_rejects_invalid_values(advisor):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llm": {"advisor": advisor}})
