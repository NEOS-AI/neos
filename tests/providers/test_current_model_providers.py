from pathlib import Path
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


def test_provider_catalogs_are_derived_from_the_model_catalog(monkeypatch):
    """카탈로그를 바꾸면 list_models()가 따라온다 — 하드코딩이 아니다."""
    monkeypatch.setattr(
        "neos.providers.anthropic.models_for_provider",
        lambda provider: ["sentinel-anthropic"] if provider == "anthropic" else [],
    )
    assert AnthropicProvider.__new__(AnthropicProvider).list_models() == [
        "sentinel-anthropic"
    ]


def test_openai_catalog_is_derived_from_the_model_catalog(monkeypatch):
    monkeypatch.setattr(
        "neos.providers.openai.models_for_provider",
        lambda provider: ["sentinel-openai"] if provider == "openai" else [],
    )
    assert OpenAIProvider.__new__(OpenAIProvider).list_models() == ["sentinel-openai"]


def test_provider_catalogs_include_current_and_legacy_models():
    anthropic_models = AnthropicProvider.__new__(AnthropicProvider).list_models()
    openai_models = OpenAIProvider.__new__(OpenAIProvider).list_models()

    assert {"claude-sonnet-5", "claude-opus-5"} <= set(anthropic_models)
    assert {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
    } <= set(anthropic_models)
    assert {"gpt-5.6-terra", "gpt-5.6-sol"} <= set(openai_models)


def test_retired_unpriced_models_are_not_offered():
    """가격 없이 선택 가능하던 모델들은 목록에서 빠졌다.

    이들의 비용은 0으로 집계돼 `neos_llm_cost_usd`를 낮췄다. 각각
    claude-sonnet-5 / claude-opus-5 / gpt-5.6-terra / gpt-5.6-sol로 대체했다.
    """
    anthropic_models = AnthropicProvider.__new__(AnthropicProvider).list_models()
    openai_models = OpenAIProvider.__new__(OpenAIProvider).list_models()

    assert {"claude-sonnet-4-6", "claude-opus-4-6"}.isdisjoint(anthropic_models)
    assert {
        "gpt-5-mini-2025-08-07",
        "gpt-5-2025-08-07",
        "o3-mini",
        "o3",
    }.isdisjoint(openai_models)


def test_priced_only_models_stay_out_of_the_selectable_lists():
    """가격만 아는 레거시 모델을 목록에 끼워넣지 않는다 (spec §3 selectable)."""
    anthropic_models = AnthropicProvider.__new__(AnthropicProvider).list_models()
    openai_models = OpenAIProvider.__new__(OpenAIProvider).list_models()

    assert "claude-opus-4-5-20251101" not in anthropic_models
    assert "claude-3-5-sonnet-20240620" not in anthropic_models
    assert "gpt-4o" not in openai_models
    assert "gpt-3.5-turbo" not in openai_models


def test_recommendations_are_derived_from_the_model_catalog(monkeypatch):
    monkeypatch.setattr(
        "neos.utils.llm_factory.tiers_for_provider",
        lambda provider: {"balanced": f"sentinel-{provider}"},
    )
    assert get_recommended_models("anthropic") == {"balanced": "sentinel-anthropic"}


def test_recommendations_use_current_everyday_and_powerful_models():
    assert get_recommended_models("anthropic")["balanced"] == "claude-sonnet-5"
    assert get_recommended_models("anthropic")["powerful"] == "claude-opus-5"
    assert get_recommended_models("openai")["balanced"] == "gpt-5.6-terra"
    assert get_recommended_models("openai")["powerful"] == "gpt-5.6-sol"


def test_recommendations_for_unknown_provider_are_empty():
    assert get_recommended_models("no-such-provider") == {}


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

    with pytest.raises(ValueError, match="budget_tokens.*adaptive"):
        provider.create_llm(
            model="claude-sonnet-5",
            temperature=0.7,
            max_tokens=8192,
            thinking={"type": "enabled", "budget_tokens": 2048},
        )


def test_unregistered_anthropic_model_keeps_budgeted_thinking(monkeypatch):
    """카탈로그에 없는 Anthropic 모델은 레거시 분기를 유지한다 (spec §4)."""
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=True, max_thinking_length=2048),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-9-not-in-catalog",
            temperature=0.7,
            max_tokens=8192,
        )

    params = chat_anthropic.call_args.kwargs
    assert params["temperature"] == 1.0
    assert params["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_thinking_contract_drives_normalization_not_the_model_name(monkeypatch):
    """계약이 adaptive면 이름과 무관하게 adaptive 경로를 탄다.

    Claude 5.5 / 6이 나와도 YAML 한 줄로 끝나는지를 고정한다.
    """
    from neos.config.model_config import ThinkingContract

    monkeypatch.setattr(
        "neos.providers.anthropic.thinking_contract",
        lambda model: ThinkingContract.ADAPTIVE,
    )
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        _anthropic_settings(thinking_enabled=False, max_thinking_length=0),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-sonnet-7-hypothetical",
            temperature=0.7,
            max_tokens=8192,
        )

    params = chat_anthropic.call_args.kwargs
    assert "temperature" not in params
    assert params["thinking"] == {"type": "adaptive"}


def test_version_baked_identifiers_are_gone():
    """`is_claude_5`가 shim으로도 남지 않는다 (spec §4)."""
    import neos.config.model_routing as model_routing

    assert not hasattr(model_routing, "is_claude_5")
    assert "is_claude_5" not in Path("neos/providers/anthropic.py").read_text(
        encoding="utf-8"
    )
