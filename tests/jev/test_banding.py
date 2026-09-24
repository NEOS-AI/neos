"""단조 축소(monotone narrowing) 불변식 -- 로드맵 §12.2 ②.

Jev 는 정적 정책 결과를 **좁히기만** 한다. `DENY → ALLOW` 도
`REQUIRE_APPROVAL → ALLOW` 도 만들 수 없다. 확률이 denylist 를 이기면
게이트가 아니라 우회로다(S11).

이 파일의 마지막 테스트가 **변이 테스트**다. 불변식 검사가 실제로 무는지를
보지 않고 세운 게이트는 없느니만 못하다 -- K2b 의 부분 문자열 단언이 정확히
이 자리의 함정이었다.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from neos.coding.domain.approvals import ApprovalPolicyOutcome
from neos.jev.banding import (
    BAND_FLOOR,
    RiskBand,
    is_at_least_as_strict,
    narrow,
)

pytestmark = pytest.mark.no_db


def test_mid_band_lifts_allow_to_require_approval() -> None:
    """중간대는 정보다 -- "애매하다"는 좁힐 근거가 된다(§12.4)."""
    assert (
        narrow(ApprovalPolicyOutcome.ALLOW, RiskBand.MID)
        is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    )


def _check_never_widens(
    candidate: Callable[[ApprovalPolicyOutcome, RiskBand], ApprovalPolicyOutcome],
) -> None:
    """모든 (R₀, 밴드) 조합에서 결과가 R₀ 보다 느슨하지 않은지 본다.

    검사를 테스트 쪽 헬퍼로 두는 이유는 **변이체에게도 똑같이 먹여야** 하기
    때문이다. 아래 변이 테스트가 이 함수의 유일한 존재 이유다.
    """
    for static_outcome in ApprovalPolicyOutcome:
        for band in RiskBand:
            narrowed = candidate(static_outcome, band)
            assert is_at_least_as_strict(narrowed, static_outcome), (
                f"{band} 밴드가 {static_outcome} 를 {narrowed} 로 넓혔다"
            )


def test_narrow_never_widens_the_static_outcome() -> None:
    _check_never_widens(narrow)


def test_the_invariant_check_bites_a_jev_trusting_mutant() -> None:
    """확률을 그대로 믿는 변이체를 검사가 **잡는가**.

    이것이 없으면 위 테스트는 "초록이니까 안전하다"만 말하고, 검사가 사실은
    아무것도 재지 않아도 초록이다. 무는지 보지 않고 세운 게이트는 없느니만
    못하다(§14).
    """

    def trusts_jev(
        static_outcome: ApprovalPolicyOutcome, band: RiskBand
    ) -> ApprovalPolicyOutcome:
        del static_outcome  # R₀ 를 버린다 -- 정확히 S11 이 막는 고장
        return BAND_FLOOR[band]

    with pytest.raises(AssertionError, match="넓혔다"):
        _check_never_widens(trusts_jev)
