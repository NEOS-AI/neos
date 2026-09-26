import pytest

from neos.providers.effort import effort_request_fields

pytestmark = pytest.mark.no_db


def test_anthropic_goes_to_output_config() -> None:
    assert effort_request_fields("anthropic", "high") == {
        "output_config": {"effort": "high"}
    }


def test_openai_goes_to_reasoning_effort() -> None:
    assert effort_request_fields("openai", "none") == {"reasoning_effort": "none"}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
def test_nothing_resolved_means_no_key_at_all(provider: str) -> None:
    assert effort_request_fields(provider, None) == {}


def test_a_provider_without_effort_refuses_a_value() -> None:
    with pytest.raises(ValueError, match="gemini"):
        effort_request_fields("gemini", "low")


def test_anthropic_create_llm_carries_effort(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "k")
    llm = mod.AnthropicProvider().create_llm(
        "claude-sonnet-5", 0.1, 1000, effort="high"
    )
    assert llm.output_config == {"effort": "high"}


def test_anthropic_create_llm_without_effort_sends_no_output_config(monkeypatch) -> None:
    from neos.providers import anthropic as mod

    monkeypatch.setattr(mod.settings, "ANTHROPIC_API_KEY", "k")
    llm = mod.AnthropicProvider().create_llm("claude-sonnet-5", 0.1, 1000)
    assert not llm.output_config


def test_openai_create_llm_carries_reasoning_effort(monkeypatch) -> None:
    from neos.providers import openai as mod

    monkeypatch.setattr(mod.settings, "OPENAI_API_KEY", "k")
    llm = mod.OpenAIProvider().create_llm("gpt-6-sol", 0.1, 1000, effort="low")
    assert llm.reasoning_effort == "low"
