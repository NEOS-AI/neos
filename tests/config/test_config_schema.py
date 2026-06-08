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


def test_schema_defaults_match_current_runtime_policy():
    config = AppConfig()

    assert config.environment == "development"
    assert config.api.debug is False
    assert config.api.v1_prefix == "/api/v1"
    assert config.research_harness.direct_repair.enabled is False


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
