"""D-L1 의 순서 -- 밴딩은 unattended 접기 **앞**에 온다(§12.4).

`evaluate_approval` 은 이미 "unattended 런에서 REQUIRE_APPROVAL 은 DENY" 를
갖고 있다. D-L1 의 "unattended 중간대는 DENY" 는 그 규칙을 **다시 적는 것이
아니라**, 밴딩을 그 접기 앞에 꽂아서 얻는 것이다.

순서가 뒤집히면 조용히 틀린다 -- 중간대가 REQUIRE_APPROVAL 로 남고, 승인할
사람이 없는 런에서 영원히 매달린다. 그래서 이 테스트는 **순서만** 겨눈다.
"""

from __future__ import annotations

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalPolicyOutcome,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall
from neos.jev.banding import RiskBandThresholds
from neos.jev.gate import RiskScore, evaluate_approval_with_jev

pytestmark = pytest.mark.no_db

THRESHOLDS = RiskBandThresholds(low_below=0.3, high_at_or_above=0.7)


class StubScorer:
    def __init__(self, probability: float) -> None:
        self._probability = probability

    async def score_tool_risk(self, state: object) -> RiskScore:
        del state
        return RiskScore(
            probability=self._probability,
            model="jev-test-pin",
            rubric_digest="d" * 64,
        )


def read_only_call() -> ValidatedToolCall:
    """정적 정책이 ALLOW 를 내는 호출. 밴딩이 없으면 그대로 통과한다."""
    return ValidatedToolCall(name="read_file", input={"path": "a.txt"}, risk=ToolRisk.READ_ONLY)


async def test_a_mid_band_becomes_deny_on_an_unattended_run() -> None:
    """승인할 사람이 없는 런에서 "사람에게 묻는다"는 답이 아니다(D-L1)."""
    decision = await evaluate_approval_with_jev(
        read_only_call(),
        ApprovalGate(unattended=True),
        scorer=StubScorer(0.5),
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.outcome is ApprovalPolicyOutcome.DENY


async def test_the_same_mid_band_asks_a_person_on_an_attended_run() -> None:
    decision = await evaluate_approval_with_jev(
        read_only_call(),
        ApprovalGate(unattended=False),
        scorer=StubScorer(0.5),
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL


async def test_shadow_mode_leaves_an_unattended_run_untouched() -> None:
    """L2 에서 행동이 바뀌면 그건 이미 L3 이다 -- 접기까지 포함해서."""
    decision = await evaluate_approval_with_jev(
        read_only_call(),
        ApprovalGate(unattended=True),
        scorer=StubScorer(0.5),
        thresholds=THRESHOLDS,
        enforce=False,
    )
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW
    assert decision.event is not None
    # 접기까지 거친 값이다. 접기 전 값을 실으면 L3 을 켤지 보는 사람이
    # "실제로 무슨 일이 일어났을 것인가"를 못 본다 -- unattended 런에서
    # 그 둘은 REQUIRE_APPROVAL 과 DENY 만큼 다르다.
    # 문자열이다. payload 는 원장에 그대로 들어가므로 JSON 가능한 값만 싣는다
    # -- enum 을 실으면 인메모리 테스트는 통과하고 진짜 원장에서 터진다.
    assert decision.event["would_be_outcome"] == "deny"


async def test_an_unattended_run_that_jev_cannot_answer_keeps_the_static_outcome() -> None:
    """폴백의 최악은 "Jev 도입 이전"이지 "정책 없음"이 아니다(§12.4)."""

    class FailingScorer:
        async def score_tool_risk(self, state: object) -> RiskScore:
            del state
            raise TimeoutError("jev did not answer")

    decision = await evaluate_approval_with_jev(
        read_only_call(),
        ApprovalGate(unattended=True),
        scorer=FailingScorer(),
        thresholds=THRESHOLDS,
        enforce=True,
    )
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW
    assert decision.event is not None
    assert decision.event["kind"] == "jev_unavailable"
