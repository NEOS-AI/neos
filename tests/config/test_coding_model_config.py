import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig, CodingModelConfig


def real_config(**overrides):
    data = {
        "environment": "development",
        "coding_model": {"enabled": True, "model": "claude-test"},
        "sandbox": {"enabled": True},
        "secrets": {"anthropic_api_key": "secret-value"},
    }
    data.update(overrides)
    return data


def priced_real_config(**overrides):
    data = real_config()
    data["coding_model"].update({
        "input_cost_micros_per_million": 3_000_000,
        "output_cost_micros_per_million": 15_000_000,
    })
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_timeout_sec", 0),
        ("tool_timeout_sec", 0),
        ("max_turns", 0),
        ("max_tool_calls", 0),
        ("max_consecutive_tool_errors", 0),
        ("max_output_tokens", 0),
        ("max_transcript_bytes", 0),
        ("max_cost_usd", 0),
        ("mutation_snapshot_interval", 0),
    ],
)
def test_coding_model_budgets_must_be_positive(field, value) -> None:
    with pytest.raises(ValidationError):
        CodingModelConfig.model_validate({field: value})


def test_command_allowlist_rejects_empty_or_malformed_entries() -> None:
    with pytest.raises(ValidationError, match="command allowlist"):
        CodingModelConfig(command_allowlist=["pytest", "bad command"])
    with pytest.raises(ValidationError, match="command allowlist"):
        CodingModelConfig(command_enabled=True, command_allowlist=[])


def test_disabled_commands_require_an_empty_allowlist() -> None:
    config = CodingModelConfig(command_enabled=False, command_allowlist=[])
    assert config.command_allowlist == []
    with pytest.raises(ValidationError, match="empty command allowlist"):
        CodingModelConfig(command_enabled=False, command_allowlist=["git"])


def test_real_loop_requires_sandbox_and_credential() -> None:
    with pytest.raises(ValidationError, match="coding real loop requires"):
        AppConfig.model_validate(real_config(sandbox={"enabled": False}))
    with pytest.raises(ValidationError, match="coding real loop requires"):
        AppConfig.model_validate(real_config(secrets={}))


def test_real_loop_requires_nonzero_explicit_prices() -> None:
    with pytest.raises(ValidationError, match="positive input and output prices"):
        AppConfig.model_validate(real_config())


def test_real_loop_accepts_explicit_prices() -> None:
    config = AppConfig.model_validate(priced_real_config())
    assert config.coding_model.input_cost_micros_per_million == 3_000_000
    assert config.coding_model.output_cost_micros_per_million == 15_000_000


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_real_loop_requires_docker_in_deployed_environments(environment) -> None:
    with pytest.raises(ValidationError, match="Docker sandbox"):
        AppConfig.model_validate(priced_real_config(environment=environment))


def test_anthropic_secret_is_redacted() -> None:
    config = AppConfig.model_validate(priced_real_config())
    assert "secret-value" not in repr(config)
    assert "secret-value" not in str(config)
