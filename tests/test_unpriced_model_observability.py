"""가격 미상 모델의 비용 0 집계가 관측 가능한지 검증한다.

카탈로그는 allowlist가 아니므로 등록되지 않은 모델도 요청은 통과한다.
그 비용은 0으로 집계되어 `neos_llm_cost_usd`를 실제보다 낮게 만든다.

한때 선택 가능하면서 가격이 없는 모델이 6개 있었다. 전부 은퇴시켜 지금은
0개이며, 그 상태를 `test_no_selectable_model_is_unpriced`가 지킨다. 카운터는
그 불변식이 깨졌을 때와, 저장된 대화가 은퇴 모델을 가리킬 때를 위한
안전망이다 — 로그 경고만으로는 몇 주 뒤 비용 리포트를 의심한 사람이
찾을 수 없다.
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


def test_no_selectable_model_is_unpriced() -> None:
    """카운터가 울릴 일이 애초에 없어야 정상이다.

    가격 없이 선택 가능하던 모델 6개는 은퇴시켰다. 카운터는 그 상태가
    깨졌을 때를 위한 안전망이지, 상시 발생하는 정상 동작이 아니다.
    """
    unpriced = [
        f"{provider}/{model}"
        for provider in ("anthropic", "openai")
        for model in models_for_provider(provider)
        if pricing_for(provider, model) is None
    ]

    assert unpriced == [], (
        f"these selectable models would aggregate as zero cost: {sorted(unpriced)}"
    )


def test_retired_models_still_increment_if_someone_names_them() -> None:
    """저장된 대화가 은퇴 모델을 가리켜도 조용히 지나가지 않는다.

    카탈로그는 allowlist가 아니므로 요청 자체는 통과한다. 다만 그 비용이
    0으로 잡히는 사실은 카운터로 드러나야 한다.
    """
    for provider, model in (
        ("anthropic", "claude-sonnet-4-6"),
        ("anthropic", "claude-opus-4-6"),
        ("openai", "gpt-5-mini-2025-08-07"),
        ("openai", "gpt-5-2025-08-07"),
        ("openai", "o3"),
        ("openai", "o3-mini"),
    ):
        before = _counter_value(provider, model)
        assert CostCalculator._get_default_pricing(provider, model) is None
        assert _counter_value(provider, model) == before + 1, (
            f"retired {provider}/{model} aggregates as zero cost without "
            "incrementing neos_llm_unpriced_calls_total"
        )
