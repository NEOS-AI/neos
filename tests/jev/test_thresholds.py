"""확률 -> 밴드. 임계값은 **코드에 없다**(로드맵 §12.4 · §9 매직넘버 금지).

쿡북의 `<0.30 / >0.70` 을 그대로 들여오지 않는다. 기본값은 L1·L2 실측이
정하고, 그때까지 이 타입은 **호출자가 준 값만** 쓴다.
"""

from __future__ import annotations

import pytest

from neos.jev.banding import RiskBand, RiskBandThresholds, band_for

pytestmark = pytest.mark.no_db


def thresholds(low: float = 0.3, high: float = 0.7) -> RiskBandThresholds:
    return RiskBandThresholds(low_below=low, high_at_or_above=high)


def test_probability_at_the_high_threshold_is_high_band() -> None:
    """경계는 닫힌 쪽이다 -- `>=` 여야 임계값 자신이 어느 밴드인지 정해진다."""
    assert band_for(0.7, thresholds()) is RiskBand.HIGH


def test_probability_at_the_low_threshold_is_mid_band() -> None:
    """LOW 는 `p < low_below` 다. 임계값 자신은 LOW 가 아니라 중간대다."""
    assert band_for(0.3, thresholds()) is RiskBand.MID


def test_probability_below_the_low_threshold_is_low_band() -> None:
    assert band_for(0.29, thresholds()) is RiskBand.LOW


def test_inverted_thresholds_are_rejected() -> None:
    """뒤집힌 임계값은 중간대를 없애는 게 아니라 **말이 안 된다**."""
    with pytest.raises(ValueError, match="low_below"):
        RiskBandThresholds(low_below=0.8, high_at_or_above=0.2)


def test_thresholds_outside_the_unit_interval_are_rejected() -> None:
    """Noul 은 확률이다. 1.4 를 받는 임계값은 영원히 닿지 않는 밴드를 만든다."""
    with pytest.raises(ValueError, match="0 과 1"):
        RiskBandThresholds(low_below=0.3, high_at_or_above=1.4)


def test_a_probability_outside_the_unit_interval_is_rejected() -> None:
    """프로바이더가 범위를 벗어난 값을 주면 **조용히 밴딩하지 않는다**."""
    with pytest.raises(ValueError, match="0 과 1"):
        band_for(1.2, thresholds())
