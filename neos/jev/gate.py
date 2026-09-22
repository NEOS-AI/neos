"""도구 위험 밴딩의 오케스트레이션 -- 로드맵 §12.2 ② · §12.4 · S11~S13.

이 모듈이 아는 것은 **순서**다. 확률을 밴드로 바꾸는 것은 `banding`,
확률을 구해 오는 것은 `ToolRiskScorer` 구현체의 일이고, 여기서는 셋을
정해진 차례로 엮는다.

    R₀ == DENY  ──▶ 끝. Jev 를 부르지 않는다(§12.2 ②)
    R₀ != DENY  ──▶ 확률 ──▶ 밴드 ──▶ narrow(R₀, 밴드) ──▶ R₁
                     └── 실패 ──▶ R₀ 그대로 + `jev_unavailable`(D-L1)

**섀도(L2)와 게이트(L3)의 차이는 `enforce` 하나다.** 섀도에서도 이벤트는
똑같이 남고, 거기에 `would_be_outcome` 이 실린다 -- L3 을 켜는 결정은 그
필드들의 **건별 리뷰**로 내린다(§12.5 L3 의 선행).

`unattended` 는 여기서 다루지 않는다. D-L1 의 "unattended 중간대는 DENY" 는
`evaluate_approval` 이 이미 갖고 있는 규칙이고(REQUIRE_APPROVAL → DENY),
밴딩을 그 접기 **앞**에 꽂으면 그대로 성립한다. 규칙을 여기에 한 번 더 적으면
사본이 둘이 되고, 고침은 한쪽에만 도착한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalPolicyOutcome,
    evaluate_static_approval,
    fold_for_unattended,
)
from neos.jev.banding import RiskBandThresholds, band_for, narrow

if TYPE_CHECKING:
    from neos.coding.tools.registry import ValidatedToolCall

#: 원장 이벤트 kind. 트랙 C 의 짝 규칙이 이 두 문자열을 읽는다.
JEV_RISK_SCORED = "jev_risk_scored"
JEV_UNAVAILABLE = "jev_unavailable"


@dataclass(frozen=True, slots=True)
class RiskScore:
    """Noul 한 번의 결과.

    확률만으로는 판정을 재현할 수 없다. 해소된 모델 id 와 루브릭 digest 를
    확률과 **같은 객체**에 두는 것이 S13 을 지키는 가장 싼 방법이다 -- 따로
    두면 이벤트를 쓰는 자리에서 하나를 빠뜨릴 수 있다.
    """

    probability: float
    model: str
    rubric_digest: str


class ToolRiskScorer(Protocol):
    """확률을 구해 오는 쪽. SDK 를 아는 것은 이 Protocol 의 구현체뿐이다."""

    async def score_tool_risk(self, state: Mapping[str, object]) -> RiskScore: ...


@dataclass(frozen=True, slots=True)
class BandedDecision:
    """밴딩을 거친 결과와, 원장에 실을 이벤트 payload.

    이벤트를 **여기서 쓰지 않고 돌려주는** 이유는 원장 작성자가 하나여야 하기
    때문이다(P2). 이 모듈은 제안하고, 부르는 쪽이 쓴다.
    """

    outcome: ApprovalPolicyOutcome
    event: dict[str, Any] | None


async def apply_tool_risk_banding(
    static_outcome: ApprovalPolicyOutcome,
    *,
    scorer: ToolRiskScorer,
    state: Mapping[str, object],
    thresholds: RiskBandThresholds,
    enforce: bool,
) -> BandedDecision:
    """정적 정책 결과에 Jev 밴딩을 얹는다. 좁히는 방향으로만.

    Args:
        static_outcome: 정적 정책이 낸 R₀.
        scorer: 확률을 구해 오는 쪽.
        state: 판단 대상. Jev 의 `state` 로 그대로 간다.
        thresholds: 밴드 경계. settings 에서 온다 -- 기본값은 없다(§9).
        enforce: True 면 L3(실제 차단), False 면 L2(섀도, 기록만).
    """
    if static_outcome is ApprovalPolicyOutcome.DENY:
        return BandedDecision(outcome=static_outcome, event=None)

    try:
        score = await scorer.score_tool_risk(state)
    except Exception as error:  # noqa: BLE001 -- 폴백 조건은 "대답하지 않았다" 전부다
        return BandedDecision(
            outcome=static_outcome,
            event={
                "kind": JEV_UNAVAILABLE,
                "reason": type(error).__name__,
                "static_outcome": static_outcome,
                "enforced": enforce,
            },
        )

    band = band_for(score.probability, thresholds)
    narrowed = narrow(static_outcome, band)
    return BandedDecision(
        outcome=narrowed if enforce else static_outcome,
        event={
            "kind": JEV_RISK_SCORED,
            "probability": score.probability,
            "band": str(band),
            "low_below": thresholds.low_below,
            "high_at_or_above": thresholds.high_at_or_above,
            "rubric_digest": score.rubric_digest,
            "model": score.model,
            "static_outcome": static_outcome,
            "would_be_outcome": narrowed,
            "enforced": enforce,
        },
    )


async def evaluate_approval_with_jev(
    call: "ValidatedToolCall",
    gate: ApprovalGate | None = None,
    *,
    scorer: ToolRiskScorer,
    thresholds: RiskBandThresholds,
    enforce: bool,
) -> BandedDecision:
    """정적 정책 → Jev 밴딩 → unattended 접기. **이 순서가 계약이다.**

    `evaluate_approval` 과 같은 자리를 지나되, 접기 앞에 밴딩 한 단계가
    끼어든다. 접기를 여기서 다시 구현하지 않고 `fold_for_unattended` 를
    부르는 것이 요점이다 -- 규칙 사본이 둘이 되면 고침은 한쪽에만 도착한다.

    정적 판정이 터지면 `evaluate_approval` 과 똑같이 DENY 로 닫는다. Jev 가
    터지는 것과 정적 정책이 터지는 것은 **다른 사건**이다: 앞은 축소할 근거가
    없어 R₀ 가 서고, 뒤는 R₀ 자체가 없다.
    """
    resolved = gate or ApprovalGate()
    try:
        static_outcome = evaluate_static_approval(call, resolved)
    except Exception:  # noqa: BLE001 -- evaluate_approval 과 같은 계약
        return BandedDecision(outcome=ApprovalPolicyOutcome.DENY, event=None)

    banded = await apply_tool_risk_banding(
        static_outcome,
        scorer=scorer,
        state=jev_state(call),
        thresholds=thresholds,
        enforce=enforce,
    )

    event = banded.event
    if event is not None and "would_be_outcome" in event:
        event = dict(event)
        event["would_be_outcome"] = fold_for_unattended(
            event["would_be_outcome"], resolved
        )
    return BandedDecision(
        outcome=fold_for_unattended(banded.outcome, resolved),
        event=event,
    )


def jev_state(call: "ValidatedToolCall") -> dict[str, Any]:
    """Jev 에게 보여 줄 판단 대상.

    도구 이름과 입력만 보낸다. 워크스페이스 내용이나 대화는 보내지 않는다 --
    보내기 시작하면 무엇이 나갔는지 이벤트로 복원할 수 없고, 그러면 그 판정은
    재현할 수 없다(S13).
    """
    return {"tool": call.name, "input": dict(call.input)}
