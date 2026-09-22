"""확률 -> 밴드 -> 축소. 단조 축소 불변식이 사는 곳이다(로드맵 §12.2 ②).

    정적 정책 ──▶ R₀ ──(R₀ == DENY 면 Jev 를 부르지 않는다)──▶ 끝
                   │
                   └── Jev 밴딩 ──▶ R₁ ∈ {R₀, 더 좁은 것}

`narrow` 는 **절대 넓히지 않는다**. 밴드가 아무리 낮아도 R₀ 보다 느슨한 값을
돌려주지 않는다 -- 그래서 반환은 "밴드가 말하는 값"이 아니라 **R₀ 와 밴드
바닥 중 더 엄한 쪽**이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from neos.coding.domain.approvals import ApprovalPolicyOutcome


class RiskBand(StrEnum):
    """Noul 확률이 떨어지는 세 구간. 임계값은 여기 없다(settings 가 정한다)."""

    LOW = "low"
    MID = "mid"
    HIGH = "high"


#: 엄격도 순서. 큰 값이 더 엄하다. `narrow` 가 max 를 취하는 축이다.
_STRICTNESS: dict[ApprovalPolicyOutcome, int] = {
    ApprovalPolicyOutcome.ALLOW: 0,
    ApprovalPolicyOutcome.REQUIRE_APPROVAL: 1,
    ApprovalPolicyOutcome.DENY: 2,
}

#: 밴드가 요구하는 **최소** 엄격도. 이것이 결과가 아니라 바닥인 것이 요점이다.
BAND_FLOOR: dict[RiskBand, ApprovalPolicyOutcome] = {
    RiskBand.LOW: ApprovalPolicyOutcome.ALLOW,
    RiskBand.MID: ApprovalPolicyOutcome.REQUIRE_APPROVAL,
    RiskBand.HIGH: ApprovalPolicyOutcome.DENY,
}


@dataclass(frozen=True, slots=True)
class RiskBandThresholds:
    """밴드 경계. **기본값이 없다** -- 호출자가 settings 에서 실어 와야 한다.

    쿡북의 `0.30/0.70` 을 여기에 적지 않는 것이 요점이다(§12.4). 기본값을
    한 번 적어 두면 아무도 그것이 실측인지 인용인지 다시 묻지 않는다.

    경계는 반열린 구간이다 -- `p < low_below` 가 LOW, `p >= high_at_or_above`
    가 HIGH, 나머지가 중간대다. 임계값 자신이 어느 쪽인지 코드가 정해 둬야
    판정을 재현할 수 있다(S13).
    """

    low_below: float
    high_at_or_above: float

    def __post_init__(self) -> None:
        for name, value in (
            ("low_below", self.low_below),
            ("high_at_or_above", self.high_at_or_above),
        ):
            _require_probability(value, name)
        if self.low_below > self.high_at_or_above:
            raise ValueError(
                "low_below 는 high_at_or_above 보다 클 수 없다: "
                f"{self.low_below} > {self.high_at_or_above}"
            )


def _require_probability(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} 는 0 과 1 사이여야 한다: {value}")


def band_for(probability: float, thresholds: RiskBandThresholds) -> RiskBand:
    """Noul 확률이 떨어지는 밴드.

    범위를 벗어난 확률은 **거절한다**. 클램프하면 프로바이더가 이상한 값을
    보내기 시작한 날 게이트가 조용히 한쪽으로 쏠린다.
    """
    _require_probability(probability, "probability")
    if probability < thresholds.low_below:
        return RiskBand.LOW
    if probability >= thresholds.high_at_or_above:
        return RiskBand.HIGH
    return RiskBand.MID


def is_at_least_as_strict(
    outcome: ApprovalPolicyOutcome, reference: ApprovalPolicyOutcome
) -> bool:
    """`outcome` 이 `reference` 만큼, 또는 그보다 엄한가.

    단조 축소 불변식의 술어다. 테스트가 이것을 **공유해서** 쓴다 -- 엄격도
    순서를 테스트가 따로 적으면 사본이 둘이 되고, 고침은 한쪽에만 도착한다.
    """
    return _STRICTNESS[outcome] >= _STRICTNESS[reference]


def narrow(
    static_outcome: ApprovalPolicyOutcome, band: RiskBand
) -> ApprovalPolicyOutcome:
    """R₀ 와 밴드 바닥 중 더 엄한 쪽. 결코 R₀ 보다 느슨하지 않다."""
    floor = BAND_FLOOR[band]
    return max(static_outcome, floor, key=lambda outcome: _STRICTNESS[outcome])
