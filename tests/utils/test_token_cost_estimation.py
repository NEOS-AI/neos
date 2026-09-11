"""토큰 비용 추정이 모델 카탈로그를 단일 원천으로 쓰는지 검증한다.

이전에는 `neos/utils/token_counter.py`와
`neos/agents/search_agents/hyper_deep_research/utils/token_counter.py`가
각각 per-1K 가격표를 들고 있었다. 두 표 모두 부분 문자열 매칭 + "모르면 GPT-4"
기본값이라, 현행 주 모델인 claude-sonnet-5가 $30/$60 per 1M로 계산됐다
(실제 $3/$15 — 입력 10배, 출력 4배 과대).
"""

import pytest

from neos.agents.search_agents.hyper_deep_research.utils.token_counter import (
    TokenCounter as HdrTokenCounter,
)
from neos.config.model_config import pricing_for
from neos.utils.token_counter import TokenCounter, estimate_cost_usd

pytestmark = pytest.mark.no_db


def test_estimate_uses_catalog_pricing() -> None:
    # claude-sonnet-5: input $3.00 / output $15.00 per 1M
    cost = estimate_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000)

    assert cost == pytest.approx(18.0)


def test_estimate_scales_linearly_with_tokens() -> None:
    cost = estimate_cost_usd("claude-sonnet-5", 1000, 500)

    # (1000 * 3.00 + 500 * 15.00) / 1e6
    assert cost == pytest.approx((1000 * 3.00 + 500 * 15.00) / 1_000_000)


def test_estimate_matches_the_catalog_for_every_priced_model() -> None:
    """추정기가 카탈로그와 다른 숫자를 쓰지 않는다."""
    for provider, model in (
        ("anthropic", "claude-sonnet-5"),
        ("anthropic", "claude-opus-5"),
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-5.6-terra"),
        ("openai", "gpt-5.6-sol"),
        ("openai", "gpt-6-astra"),
        ("openai", "gpt-4o"),
    ):
        pricing = pricing_for(provider, model)
        assert pricing is not None, f"{model} lost its catalog pricing"

        expected = (1000 * pricing.input + 1000 * pricing.output) / 1_000_000

        assert estimate_cost_usd(model, 1000, 1000) == pytest.approx(expected)


def test_unknown_model_estimates_zero_and_warns(caplog) -> None:
    """모르는 모델을 GPT-4 가격으로 추측하지 않는다.

    카탈로그 철학과 동일하게 경고 + 0으로 처리한다. 틀린 가격은 없는 가격보다
    나쁘다 — 그럴듯해 보이는 숫자는 아무도 의심하지 않는다.
    """
    with caplog.at_level("WARNING", logger="neos.utils.token_counter"):
        cost = estimate_cost_usd("some-model-nobody-priced", 1_000_000, 1_000_000)

    assert cost == 0.0
    assert any("some-model-nobody-priced" in r.message for r in caplog.records)


def test_catalog_model_without_pricing_estimates_zero(caplog) -> None:
    """카탈로그에 있지만 가격이 없는 모델도 0으로 처리한다."""
    with caplog.at_level("WARNING", logger="neos.utils.token_counter"):
        cost = estimate_cost_usd("claude-sonnet-4-6", 1000, 1000)

    assert cost == 0.0
    assert any("claude-sonnet-4-6" in r.message for r in caplog.records)


def test_gpt_4_turbo_is_not_priced_as_plain_gpt_4() -> None:
    """부분 문자열 매칭 제거 확인.

    HDR 표는 "gpt-4"를 먼저 검사해서 `gpt-4-turbo`가 $0.03/1K(=gpt-4)로
    계산됐다. 실제 gpt-4-turbo는 $10/1M다.
    """
    turbo = pricing_for("openai", "gpt-4-turbo")
    assert turbo is not None

    cost = estimate_cost_usd("gpt-4-turbo", 1_000_000, 0)

    assert cost == pytest.approx(turbo.input)
    # 옛 동작($0.03/1K = $30/1M)과 다르다는 것을 못 박는다
    assert cost != pytest.approx(30.0)


@pytest.mark.parametrize("counter_class", [TokenCounter, HdrTokenCounter])
def test_both_token_counters_agree_with_the_shared_estimator(counter_class) -> None:
    """두 TokenCounter가 같은 원천을 쓴다 — 중복 가격표가 사라졌다."""
    counter = counter_class(model_name="claude-sonnet-5")

    cost = counter.calculate_cost(2000, 1000, "claude-sonnet-5")

    assert cost == pytest.approx(estimate_cost_usd("claude-sonnet-5", 2000, 1000))


@pytest.mark.parametrize("counter_class", [TokenCounter, HdrTokenCounter])
def test_neither_token_counter_keeps_a_private_price_table(counter_class) -> None:
    """가격표가 코드로 되살아나는 것을 막는다.

    docstring은 제외한다 — 옛 요율을 설명하는 산문은 정당하다. 검사 대상은
    실행되는 코드뿐이다.
    """
    import inspect

    method = counter_class.calculate_cost
    source = inspect.getsource(method)
    if method.__doc__:
        source = source.replace(method.__doc__, "")

    for legacy_rate in ("0.03", "0.06", "0.0015", "0.075", "0.00025"):
        assert legacy_rate not in source, (
            f"{counter_class.__module__}.{counter_class.__name__}.calculate_cost "
            f"still contains the hardcoded rate {legacy_rate} in executable code"
        )
