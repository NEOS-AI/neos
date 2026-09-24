"""이관 정합성 — 카탈로그가 이관 전 하드코딩 값과 일치하는가.

가장 큰 위험은 전사(transcription) 오류다. 절대값 단언은 영구 회귀
테스트로 남고, `_crosscheck` 표시가 붙은 테스트는 대응 하드코딩이
삭제되는 Task와 함께 제거된다.
"""

import pytest

from neos.config.model_config import (
    ThinkingContract,
    get_model_spec,
    models_for_provider,
    pricing_for,
    thinking_contract,
    tiers_for_provider,
)

pytestmark = pytest.mark.no_db


ANTHROPIC_SELECTABLE = [
    "claude-sonnet-5",
    "claude-opus-5-5",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
]

OPENAI_SELECTABLE = [
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-6-astra",
]

# 은퇴한 모델. 가격을 모르는 채로 선택 가능해서 비용이 0으로 집계됐다.
# 목록에 되살아나면 그 구멍도 함께 돌아온다.
RETIRED_MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "gpt-5-mini-2025-08-07",
    "gpt-5-2025-08-07",
    "o3-mini",
    "o3",
    # 2026-09-24: opus-5.5 · gpt-6-sol · gpt-6-luna 로 교체
    "claude-opus-5",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
]

EXPECTED_TIERS = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "balanced": "claude-sonnet-5",
        "powerful": "claude-opus-5-5",
    },
    "openai": {
        # GPT-6 에는 Terra 급이 없다: Sol 이 balanced·powerful, Luna 가 fast
        "fast": "gpt-6-luna",
        "balanced": "gpt-6-sol",
        "powerful": "gpt-6-sol",
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
    ("openai", "gpt-6-sol"): (2.00, 10.00, 2.50, 0.20),
    ("openai", "gpt-6-luna"): (0.10, 0.50, 0.125, 0.01),
    ("openai", "gpt-6-astra"): (10.00, 50.00, 12.50, 1.00),
    ("openai", "gpt-4o"): (2.50, 10.00, 0.0, 0.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.60, 0.0, 0.0),
    ("openai", "gpt-4-turbo"): (10.00, 30.00, 0.0, 0.0),
    ("openai", "gpt-3.5-turbo"): (0.50, 1.50, 0.0, 0.0),
    ("anthropic", "claude-sonnet-5"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-opus-5-5"): (4.00, 20.00, 5.00, 0.20),
    ("anthropic", "claude-sonnet-4-5-20250929"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-3-5-sonnet-20240620"): (3.00, 15.00, 3.75, 0.30),
    ("anthropic", "claude-opus-4-5-20251101"): (15.00, 75.00, 18.75, 1.50),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.25, 1.25, 0.30, 0.03),
}

ADAPTIVE_MODELS = ["claude-sonnet-5", "claude-opus-5-5"]

BUDGETED_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
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


def test_every_selectable_model_is_priced() -> None:
    """선택 가능한 모델은 예외 없이 가격을 가져야 한다.

    가격 없는 모델을 고를 수 있으면 그 비용은 조용히 0으로 집계되고
    `neos_llm_cost_usd`가 실제보다 낮아진다(spec §1). 예전에는 그런 모델이
    6개 있었고, 이 테스트는 그 목록을 고정하기만 했다. 지금은 전부 은퇴시켰고,
    테스트도 목록 고정이 아니라 **불변식**을 지킨다.

    가격 없이 새 모델을 선택 가능하게 만들면 여기서 걸린다.
    """
    unpriced = {
        f"{provider}/{model}"
        for provider in ("anthropic", "openai")
        for model in models_for_provider(provider)
        if pricing_for(provider, model) is None
    }

    assert unpriced == set(), (
        "these models are selectable but have no price, so their cost "
        f"aggregates as zero: {sorted(unpriced)}"
    )


@pytest.mark.parametrize("model", RETIRED_MODELS)
def test_retired_models_are_gone_from_the_catalog(model: str) -> None:
    """은퇴 모델이 되살아나면 $0 집계 구멍도 함께 돌아온다."""
    assert get_model_spec(model) is None, (
        f"{model} was retired for having no price; re-adding it needs a "
        "`pricing:` block, otherwise its cost aggregates as zero"
    )


