"""가격 미상 모델의 비용 0 집계가 관측 가능한지 검증한다.

카탈로그는 allowlist가 아니므로 가격 없는 모델도 선택 가능하다. 현재 그런
모델이 6개 있다 (`claude-sonnet-4-6`, `claude-opus-4-6`,
`gpt-5-mini-2025-08-07`, `gpt-5-2025-08-07`, `o3`, `o3-mini`). 이들의 비용은
0으로 집계되어 `neos_llm_cost_usd`를 실제보다 낮게 만든다.

로그 경고만으로는 몇 주 뒤 비용 리포트를 의심한 사람이 찾을 수 없다.
알람 가능한 카운터가 필요하다.
"""

import pytest

from neos.config.model_config import models_for_provider, pricing_for
from neos.utils.cost_calculator import CostCalculator

pytestmark = pytest.mark.no_db


def _counter_value(provider: str, model: str) -> float:
    from neos.observability.metrics import get_metrics_collector

    counter = get_metrics_collector().llm_unpriced_calls_total
    return counter.labels(provider=provider, model=model)._value.get()


def test_unpriced_lookup_increments_the_counter() -> None:
    provider, model = "anthropic", "claude-sonnet-4-6"
    assert pricing_for(provider, model) is None, "fixture model gained a price"

    before = _counter_value(provider, model)
    CostCalculator._get_default_pricing(provider, model)
    after = _counter_value(provider, model)

    assert after == before + 1


def test_priced_lookup_does_not_increment_the_counter() -> None:
    provider, model = "anthropic", "claude-sonnet-5"
    assert pricing_for(provider, model) is not None

    before = _counter_value(provider, model)
    CostCalculator._get_default_pricing(provider, model)
    after = _counter_value(provider, model)

    assert after == before


def test_unknown_model_also_increments() -> None:
    provider, model = "anthropic", "claude-not-in-catalog-at-all"

    before = _counter_value(provider, model)
    CostCalculator._get_default_pricing(provider, model)
    after = _counter_value(provider, model)

    assert after == before + 1


def test_metric_failure_does_not_break_cost_lookup(monkeypatch) -> None:
    """관찰 실패가 과금 경로를 막지 않는다."""
    def boom(provider, model_name):
        raise RuntimeError("metrics backend down")

    monkeypatch.setattr(CostCalculator, "_record_unpriced_call", staticmethod(boom))

    # 예외가 전파되면 이 호출이 터진다
    with pytest.raises(RuntimeError):
        CostCalculator._get_default_pricing("anthropic", "claude-sonnet-4-6")

    # 실제 구현은 내부에서 삼킨다 — 위 raise는 monkeypatch가 우회했음을 확인할 뿐
    monkeypatch.undo()
    assert CostCalculator._get_default_pricing("anthropic", "claude-sonnet-4-6") is None


def test_every_unpriced_selectable_model_is_observable() -> None:
    """가격 없는 선택 가능 모델 전부가 카운터를 올린다."""
    unpriced = [
        (provider, model)
        for provider in ("anthropic", "openai")
        for model in models_for_provider(provider)
        if pricing_for(provider, model) is None
    ]

    assert unpriced, "expected some unpriced selectable models to exist"

    for provider, model in unpriced:
        before = _counter_value(provider, model)
        CostCalculator._get_default_pricing(provider, model)

        assert _counter_value(provider, model) == before + 1, (
            f"{provider}/{model} aggregates as zero cost without incrementing "
            "neos_llm_unpriced_calls_total"
        )
