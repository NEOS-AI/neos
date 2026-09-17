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
