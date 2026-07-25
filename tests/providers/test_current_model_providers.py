from types import SimpleNamespace
from unittest.mock import patch

import pytest

from neos.providers.anthropic import AnthropicProvider
from neos.providers.openai import OpenAIProvider
from neos.utils.llm_factory import get_recommended_models


pytestmark = pytest.mark.no_db


def _anthropic_settings(*, thinking_enabled: bool, max_thinking_length: int):
    return SimpleNamespace(
        ANTHROPIC_API_KEY="test-key",
        LLM_TIMEOUT=30,
        THINKING_BLOCKS_ENABLED=thinking_enabled,
        MAX_THINKING_LENGTH=max_thinking_length,
    )


def test_provider_catalogs_include_current_and_legacy_models():
    anthropic_models = AnthropicProvider.__new__(AnthropicProvider).list_models()
    openai_models = OpenAIProvider.__new__(OpenAIProvider).list_models()

    assert {"claude-sonnet-5", "claude-opus-5"} <= set(anthropic_models)
    assert {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    } <= set(anthropic_models)
    assert {"gpt-5.6-terra", "gpt-5.6-sol"} <= set(openai_models)
    assert {"gpt-5-mini-2025-08-07", "gpt-5-2025-08-07", "o3-mini", "o3"} <= set(
        openai_models
    )


def test_recommendations_use_current_everyday_and_powerful_models():
    assert get_recommended_models("anthropic")["balanced"] == "claude-sonnet-5"
    assert get_recommended_models("anthropic")["powerful"] == "claude-opus-5"
    assert get_recommended_models("openai")["balanced"] == "gpt-5.6-terra"
    assert get_recommended_models("openai")["powerful"] == "gpt-5.6-sol"


def test_claude_sonnet_5_uses_adaptive_thinking_without_temperature(monkeypatch):
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=False, max_thinking_length=0),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-5",
            temperature=0.7,
            max_tokens=8192,
        )

    params = chat_anthropic.call_args.kwargs
    assert "temperature" not in params
    assert params["thinking"] == {"type": "adaptive"}


def test_claude_5_can_disable_adaptive_thinking(monkeypatch):
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=True, max_thinking_length=4096),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-5",
            temperature=0.7,
            max_tokens=8192,
            disable_thinking=True,
        )

    params = chat_anthropic.call_args.kwargs
    assert "temperature" not in params
    assert params["thinking"] == {"type": "disabled"}


def test_claude_opus_5_uses_adaptive_thinking_without_sampling_parameters(monkeypatch):
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=False, max_thinking_length=0),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-opus-5",
            temperature=0.7,
            max_tokens=8192,
            top_p=0.9,
            top_k=40,
        )

    params = chat_anthropic.call_args.kwargs
    assert "temperature" not in params
    assert "top_p" not in params
    assert "top_k" not in params
    assert params["thinking"] == {"type": "adaptive"}


def test_legacy_sonnet_retains_manual_thinking_behavior(monkeypatch):
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=True, max_thinking_length=2048),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-4-5-20250929",
            temperature=0.7,
            max_tokens=8192,
        )

    params = chat_anthropic.call_args.kwargs
    assert params["temperature"] == 1.0
    assert params["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_claude_5_rejects_manual_thinking_budget(monkeypatch):
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=False, max_thinking_length=0),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with pytest.raises(ValueError, match="budget_tokens.*Claude 5"):
        provider.create_llm(
            model="claude-sonnet-5",
            temperature=0.7,
            max_tokens=8192,
            thinking={"type": "enabled", "budget_tokens": 2048},
        )
