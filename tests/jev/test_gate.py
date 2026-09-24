"""도구 위험 밴딩의 오케스트레이션 -- §12.2 ② · §12.4 D-L1 · S13.

여기서 지키는 것은 셋이다.

1. **R₀ 가 DENY 면 Jev 를 부르지 않는다.** 부르지 않으므로 폴백이 그것을 여는
   경로도 존재하지 않는다.
2. **실패는 R₀ 로 떨어지되 조용히 떨어지지 않는다**(S12). `jev_unavailable`
   없는 폴백은 §9 위반이다.
3. **판정 이벤트는 재현 가능해야 한다**(S13) -- 밴드 임계값 · 루브릭 digest ·
   해소된 모델 id.
"""

from __future__ import annotations

import pytest

from neos.coding.domain.approvals import ApprovalPolicyOutcome
from neos.jev.banding import RiskBandThresholds
from neos.jev.gate import (
    JEV_RISK_SCORED,
    JEV_UNAVAILABLE,
    RiskScore,
    apply_tool_risk_banding,
)

pytestmark = pytest.mark.no_db

THRESHOLDS = RiskBandThresholds(low_below=0.3, high_at_or_above=0.7)


class StubScorer:
    """실호출 대신 고정 확률. 스위트에 실호출이 도는 테스트는 없다(§12.2 ①)."""

    def __init__(self, probability: float) -> None:
        self._probability = probability
        self.calls = 0

    async def score_tool_risk(self, state: object) -> RiskScore:
        del state
        self.calls += 1
        return RiskScore(
            probability=self._probability,
            model="jev-test-pin",
            rubric_digest="d" * 64,
        )


class FailingScorer:
    def __init__(self) -> None:
        self.calls = 0

    async def score_tool_risk(self, state: object) -> RiskScore:
        del state
        self.calls += 1
        raise TimeoutError("jev did not answer")


async def test_a_static_deny_never_reaches_jev() -> None:
    scorer = StubScorer(0.01)
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.DENY,
        scorer=scorer,
        state={"tool": "execute.v1"},
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert scorer.calls == 0
    assert decision.outcome is ApprovalPolicyOutcome.DENY
    assert decision.event is None


async def test_shadow_mode_records_without_changing_the_outcome() -> None:
    """L2 는 기록만 한다 -- 행동이 바뀌면 그건 이미 L3 이다."""
    scorer = StubScorer(0.99)
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.ALLOW,
        scorer=scorer,
        state={"tool": "execute.v1"},
        thresholds=THRESHOLDS,
        enforce=False,
    )
    assert scorer.calls == 1
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW
    assert decision.event is not None
    assert decision.event["kind"] == JEV_RISK_SCORED
    assert decision.event["enforced"] is False
    assert decision.event["would_be_outcome"] == ApprovalPolicyOutcome.DENY


async def test_enforcing_mode_narrows_allow_to_deny_on_a_high_band() -> None:
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.ALLOW,
        scorer=StubScorer(0.99),
        state={"tool": "execute.v1"},
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.outcome is ApprovalPolicyOutcome.DENY


async def test_a_low_band_leaves_a_required_approval_alone() -> None:
    """확률이 낮아도 승인 요구를 **열지 않는다**(S11)."""
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.REQUIRE_APPROVAL,
        scorer=StubScorer(0.0),
        state={"tool": "write_file"},
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL


async def test_an_unavailable_jev_falls_back_to_the_static_outcome() -> None:
    scorer = FailingScorer()
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.ALLOW,
        scorer=scorer,
        state={"tool": "execute.v1"},
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert scorer.calls == 1
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW


async def test_the_fallback_is_loud() -> None:
    """S12. 이벤트 없는 폴백은 "조용히 바뀌는 것"의 재발이다."""
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.ALLOW,
        scorer=FailingScorer(),
        state={"tool": "execute.v1"},
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.event is not None
    assert decision.event["kind"] == JEV_UNAVAILABLE
    assert decision.event["reason"] == "TimeoutError"


async def test_the_scored_event_carries_everything_needed_to_reproduce_it() -> None:
    """S13. 임계값을 모르면 과거 판정을 재현할 수 없다 = 그 런은 표본이 아니다."""
    decision = await apply_tool_risk_banding(
        ApprovalPolicyOutcome.ALLOW,
        scorer=StubScorer(0.42),
        state={"tool": "execute.v1"},
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.event is not None
    assert decision.event["probability"] == 0.42
    assert decision.event["band"] == "mid"
    assert decision.event["low_below"] == 0.3
    assert decision.event["high_at_or_above"] == 0.7
    assert decision.event["rubric_digest"] == "d" * 64
    assert decision.event["model"] == "jev-test-pin"


def test_every_event_field_is_json_serialisable() -> None:
    """payload 는 원장에 그대로 들어간다.

    enum 을 실으면 인메모리 저장소는 받아 주고 진짜 원장에서 터진다 -- 그리고
    그때는 Jev 를 켠 런에서만 터지므로, 켜는 커밋이 아니라 켠 **뒤에** 드러난다.
    """
    import asyncio
    import json

    decision = asyncio.run(
        apply_tool_risk_banding(
            ApprovalPolicyOutcome.ALLOW,
            scorer=StubScorer(0.42),
            state={"tool": "execute.v1"},
            thresholds=THRESHOLDS,
            enforce=True,
        )
    )
    assert decision.event is not None
    json.dumps(decision.event)
