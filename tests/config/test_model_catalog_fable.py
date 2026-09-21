"""claude-fable-5-1 catalog facts (roadmap K0).

Source: Anthropic claude-api reference and its "Migrating to Claude Fable 5.1"
guide, checked 2026-09-15. Only facts stated there are asserted here.
"""

from pathlib import Path

import pytest

from neos.config.model_config import (
    ThinkingContract,
    load_catalog,
    supports_mid_conversation_system,
    supports_mid_conversation_tools,
)

pytestmark = pytest.mark.no_db

CATALOG = Path("neos/config/models.yaml")


def test_fable_5_1_facts_match_the_published_reference() -> None:
    spec = load_catalog(CATALOG).models["claude-fable-5-1"]

    assert spec.provider == "anthropic"
    assert spec.thinking is ThinkingContract.ADAPTIVE
    assert spec.context_window == 1_000_000
    assert spec.max_tokens == 128_000
    assert spec.vision is True
    assert spec.selectable is False
    assert spec.mid_conversation_system is True
    assert spec.pricing is not None
    assert spec.pricing.input == 10.00
    assert spec.pricing.output == 50.00
    assert spec.pricing.cache_creation == 12.50
    assert spec.pricing.cache_read == 0.25


def test_mid_conversation_system_support_follows_the_catalog() -> None:
    assert supports_mid_conversation_system("claude-fable-5-1")
    assert supports_mid_conversation_system("claude-opus-5")
    assert supports_mid_conversation_system("claude-opus-4-8")
    assert not supports_mid_conversation_system("claude-sonnet-5")
    assert not supports_mid_conversation_system("claude-from-the-future")


def test_mid_conversation_tools_is_enabled_only_where_it_was_verified() -> None:
    """K2b is on for the model this track targets, and nowhere else.

    The SDK confirms the beta and `defer_loading` exist, but nothing local
    says which models accept them. Every model left false keeps the old
    path, which is correct rather than merely safe.
    """
    assert supports_mid_conversation_tools("claude-fable-5-1")
    assert not supports_mid_conversation_tools("claude-opus-5")
    assert not supports_mid_conversation_tools("claude-opus-4-8")
    assert not supports_mid_conversation_tools("claude-sonnet-5")
    assert not supports_mid_conversation_tools("claude-from-the-future")
