"""이관 정합성 — 카탈로그가 이관 전 하드코딩 값과 일치하는가.

가장 큰 위험은 전사(transcription) 오류다. 절대값 단언은 영구 회귀
테스트로 남고, `_crosscheck` 표시가 붙은 테스트는 대응 하드코딩이
삭제되는 Task와 함께 제거된다.
"""

import pytest

from neos.config.model_config import (
    ThinkingContract,
    models_for_provider,
    pricing_for,
    thinking_contract,
    tiers_for_provider,
)

pytestmark = pytest.mark.no_db


ANTHROPIC_SELECTABLE = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

OPENAI_SELECTABLE = [
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5-mini-2025-08-07",
    "gpt-5-2025-08-07",
    "o3-mini",
    "o3",
]

EXPECTED_TIERS = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "balanced": "claude-sonnet-5",
        "powerful": "claude-opus-5",
    },
    "openai": {
        "fast": "gpt-5-mini-2025-08-07",
        "balanced": "gpt-5.6-terra",
        "powerful": "gpt-5.6-sol",
    },
    "gemini": {
        "fast": "gemini-2.0-flash-exp",
        "balanced": "gemini-1.5-pro-latest",
        "powerful": "gemini-1.5-pro-latest",
    },
    "ollama": {
        "fast": "llama3.1:8b",
        "balanced": "llama3.1:8b",
        "powerful": "llama3.1:70b",
    },
}

EXPECTED_PRICING = {
    ("openai", "gpt-5.6-terra"): (2.50, 15.00, 0.0, 0.0),
    ("openai", "gpt-5.6-sol"): (5.00, 30.00, 0.0, 0.0),
    ("openai", "gpt-4o"): (2.50, 10.00, 0.0, 0.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.60, 0.0, 0.0),
    ("openai", "gpt-4-turbo"): (10.00, 30.00, 0.0, 0.0),
    ("openai", "gpt-3.5-turbo"): (0.50, 1.50, 0.0, 0.0),
    ("anthropic", "claude-sonnet-5"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-opus-5"): (5.00, 25.00, 6.25, 0.50),
    ("anthropic", "claude-sonnet-4-5-20250929"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-3-5-sonnet-20240620"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-opus-4-5-20251101"): (15.00, 75.00, 18.75, 1.50),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.25, 1.25, 0.30, 0.03),
}

ADAPTIVE_MODELS = ["claude-sonnet-5", "claude-opus-5"]

BUDGETED_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-3-5-sonnet-20240620",
    "claude-opus-4-5-20251101",
]


def test_catalog_selectable_lists_match_expected_order() -> None:
    assert models_for_provider("anthropic") == ANTHROPIC_SELECTABLE
    assert models_for_provider("openai") == OPENAI_SELECTABLE


@pytest.mark.parametrize("provider", sorted(EXPECTED_TIERS))
def test_catalog_tiers_match_expected(provider: str) -> None:
    assert tiers_for_provider(provider) == EXPECTED_TIERS[provider]


@pytest.mark.parametrize(("key", "expected"), sorted(EXPECTED_PRICING.items()))
def test_catalog_pricing_matches_expected(
    key: tuple[str, str], expected: tuple[float, float, float, float]
) -> None:
    provider, model = key
    pricing = pricing_for(provider, model)

    assert pricing is not None, f"{provider}/{model} has no catalog pricing"
    assert (
        pricing.input,
        pricing.output,
        pricing.cache_creation,
        pricing.cache_read,
    ) == expected


@pytest.mark.parametrize("model", ADAPTIVE_MODELS)
def test_adaptive_thinking_models(model: str) -> None:
    assert thinking_contract(model) is ThinkingContract.ADAPTIVE


@pytest.mark.parametrize("model", BUDGETED_MODELS)
def test_budgeted_thinking_models(model: str) -> None:
    assert thinking_contract(model) is ThinkingContract.BUDGETED


def test_openai_models_declare_no_thinking_contract() -> None:
    for model in OPENAI_SELECTABLE:
        assert thinking_contract(model) is ThinkingContract.NONE


def test_every_selectable_model_without_pricing_is_known() -> None:
    """가격 미상 모델은 의도된 목록과 정확히 일치해야 한다.

    선택 가능하지만 가격이 없는 모델의 비용은 0으로 집계된다(spec §1).
    새 모델을 가격 없이 추가하면 이 테스트가 알려준다.
    """
    unpriced = {
        model
        for provider in ("anthropic", "openai")
        for model in models_for_provider(provider)
        if pricing_for(provider, model) is None
    }

    assert unpriced == {
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "gpt-5-mini-2025-08-07",
        "gpt-5-2025-08-07",
        "o3",
        "o3-mini",
    }


# ---- 교차 대조: 하드코딩이 살아 있는 동안만 (해당 Task에서 제거) ----


def test_crosscheck_list_models_against_hardcoded() -> None:
    """Task 4에서 제거 — list_models()가 카탈로그 파생이 되면 항진명제가 된다."""
    from neos.providers.anthropic import AnthropicProvider
    from neos.providers.openai import OpenAIProvider

    assert (
        AnthropicProvider.__new__(AnthropicProvider).list_models()
        == ANTHROPIC_SELECTABLE
    )
    assert OpenAIProvider.__new__(OpenAIProvider).list_models() == OPENAI_SELECTABLE


def test_crosscheck_recommended_models_against_hardcoded() -> None:
    """Task 4에서 제거."""
    from neos.utils.llm_factory import get_recommended_models

    for provider, expected in EXPECTED_TIERS.items():
        assert get_recommended_models(provider) == expected


def test_crosscheck_pricing_against_hardcoded() -> None:
    """Task 5에서 제거 — DEFAULT_PRICING과 함께."""
    from neos.utils.cost_calculator import CostCalculator

    flat = {
        (provider, model): values
        for provider, models in CostCalculator.DEFAULT_PRICING.items()
        for model, values in models.items()
    }

    assert set(flat) == set(EXPECTED_PRICING)
    for key, values in flat.items():
        expected_input, expected_output, expected_cc, expected_cr = EXPECTED_PRICING[key]
        assert values["input"] == expected_input
        assert values["output"] == expected_output
        assert values.get("cache_creation", 0.0) == expected_cc
        assert values.get("cache_read", 0.0) == expected_cr
