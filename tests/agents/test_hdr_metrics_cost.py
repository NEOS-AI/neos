"""HDR 품질 메트릭의 비용 추정이 모델 카탈로그에서 나오는지 검증한다.

이전에는 `QualityMetricsCollector.__init__`이
`llm_cost_per_1k_tokens: float = 0.015  # Default: GPT-4 pricing`을 들고 있었다.
주석은 GPT-4를 가리켰지만 GPT-4의 어느 요율도 0.015가 아니었고, 실제로 쓰이는
모델(claude-sonnet-5)과도 무관했다.
"""

import pytest

from neos.agents.search_agents.hyper_deep_research.metrics_collector import (
    QualityMetricsCollector,
)
from neos.config.model_config import pricing_for

pytestmark = pytest.mark.no_db


def test_rate_is_derived_from_the_catalog_for_a_known_model() -> None:
    pricing = pricing_for("anthropic", "claude-sonnet-5")
    assert pricing is not None

    collector = QualityMetricsCollector(
        report_id="r1", model="claude-sonnet-5"
    )

    # 호출당 토큰을 입력/출력 반반으로 가정한 blended per-1K 요율
    expected = ((pricing.input + pricing.output) / 2) / 1000

    assert collector.llm_cost_per_1k_tokens == pytest.approx(expected)


def test_explicit_rate_overrides_the_catalog() -> None:
    """운영자가 자기 요율을 넣을 수 있어야 한다."""
    collector = QualityMetricsCollector(
        report_id="r1", model="claude-sonnet-5", llm_cost_per_1k_tokens=0.5
    )

    assert collector.llm_cost_per_1k_tokens == 0.5


def test_unknown_model_yields_zero_rate_not_a_guess(caplog) -> None:
    logger_name = "neos.agents.search_agents.hyper_deep_research.metrics_collector"

    with caplog.at_level("WARNING", logger=logger_name):
        collector = QualityMetricsCollector(report_id="r1", model="not-a-real-model")

    assert collector.llm_cost_per_1k_tokens == 0.0
    assert any("not-a-real-model" in r.message for r in caplog.records)


def test_no_model_yields_zero_rate() -> None:
    """모델을 모르면 추측하지 않는다."""
    collector = QualityMetricsCollector(report_id="r1")

    assert collector.llm_cost_per_1k_tokens == 0.0


def test_estimated_cost_uses_the_derived_rate() -> None:
    collector = QualityMetricsCollector(report_id="r1", model="claude-sonnet-5")

    # _estimate_cost는 호출당 약 1000 토큰을 가정한다
    cost = collector._estimate_cost(llm_calls=10)

    assert cost == pytest.approx(10 * collector.llm_cost_per_1k_tokens)


def test_no_hardcoded_gpt4_rate_remains() -> None:
    """가격 상수가 되살아나는 것을 막는다."""
    import inspect

    source = inspect.getsource(QualityMetricsCollector.__init__)
    if QualityMetricsCollector.__init__.__doc__:
        source = source.replace(QualityMetricsCollector.__init__.__doc__, "")

    assert "0.015" not in source, (
        "QualityMetricsCollector.__init__ still hardcodes a per-1K rate"
    )
