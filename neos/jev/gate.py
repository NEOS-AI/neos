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

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalPolicyOutcome,
    evaluate_static_approval,
    fold_for_unattended,
)
from neos.jev.banding import (
    RiskBand,
    RiskBandThresholds,
    band_for,
    narrow,
)

if TYPE_CHECKING:
    from neos.coding.tools.registry import ValidatedToolCall

#: 원장 이벤트 kind. 트랙 C 의 짝 규칙이 이 두 문자열을 읽는다.
JEV_RISK_SCORED = "jev_risk_scored"
JEV_UNAVAILABLE = "jev_unavailable"
#: `jev_unavailable.reason` 중 WAF 차단. 다른 이유와 달리 R₀ 로 폴백하지 않는다(D-L3).
PROVIDER_BLOCKED = "provider_blocked"

_BAND_SEVERITY = {RiskBand.LOW: 0, RiskBand.MID: 1, RiskBand.HIGH: 2}


@dataclass(frozen=True, slots=True)
class RiskScore:
    """Noul 한 번의 결과.

    확률만으로는 판정을 재현할 수 없다. 해소된 모델 id 와 루브릭 digest 를
    확률과 **같은 객체**에 두는 것이 S13 을 지키는 가장 싼 방법이다 -- 따로
    두면 이벤트를 쓰는 자리에서 하나를 빠뜨릴 수 있다.
    """

    probability: float | None
    model: str
    rubric_digest: str
    #: 질문 이름 -> 확률. 쪼갠 루브릭(D-L2)에서 채운다. 비어 있으면 질문 하나짜리
    #: 루브릭이고 `probability` 가 그 값이다.
    probabilities: Mapping[str, float] = field(default_factory=dict)


class JevProviderBlocked(Exception):
    """프로바이더 앞단(WAF)이 요청을 막았다 -- Jev 는 **판단하지 않았다**.

    D-L3(§12.11 ②): 타임아웃이나 잘못된 키와 같은 "대답하지 않았다"로 뭉치면
    안 된다. 막힌 것은 요청 본문의 문자열이고, 그 문자열을 도구 입력에 넣는
    것은 공격자가 할 수 있다. 여느 실패처럼 R₀ 로 폴백하면 공격자가 **호출
    단위로** 게이트를 끈다.

    SDK 를 모르는 이 모듈이 정의하고, SDK 를 아는 스코어러가 분류해 던진다.
    """


class ToolRiskScorer(Protocol):
    """확률을 구해 오는 쪽. SDK 를 아는 것은 이 Protocol 의 구현체뿐이다."""

    async def score_tool_risk(self, state: Mapping[str, object]) -> RiskScore: ...


@dataclass(frozen=True, slots=True)
class JevToolRiskGate:
    """루프에 주입하는 묶음. **`None` 이 곧 off 다.**

    플래그를 루프 안에서 다시 읽지 않는다 -- 읽는 자리가 늘면 "켜졌다고 믿는
    자리"와 "실제로 켜진 자리"가 갈라진다. 조립하는 쪽이 설정을 보고 이 객체를
    만들거나 만들지 않고, 루프는 있으면 쓴다.
    """

    scorer: "ToolRiskScorer"
    #: 질문 하나짜리 루브릭이면 하나, 쪼갠 루브릭(D-L2)이면 질문 이름별.
    thresholds: "RiskBandThresholds | Mapping[str, RiskBandThresholds]"
    enforce: bool


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
    thresholds: "RiskBandThresholds | Mapping[str, RiskBandThresholds]",
    enforce: bool,
) -> BandedDecision:
    """정적 정책 결과에 Jev 밴딩을 얹는다. 좁히는 방향으로만.

    Args:
        static_outcome: 정적 정책이 낸 R₀.
        scorer: 확률을 구해 오는 쪽.
        state: 판단 대상. Jev 의 `state` 로 그대로 간다.
        thresholds: 밴드 경계. settings 에서 온다 -- 기본값은 없다(§9).
            쪼갠 루브릭이면 질문 이름별 경계다.
        enforce: True 면 L3(실제 차단), False 면 L2(섀도, 기록만).
    """
    if static_outcome is ApprovalPolicyOutcome.DENY:
        return BandedDecision(outcome=static_outcome, event=None)

    try:
        score = await scorer.score_tool_risk(state)
    except JevProviderBlocked:
        return _blocked(static_outcome, enforce=enforce)
    except Exception as error:  # noqa: BLE001 -- 폴백 조건은 "대답하지 않았다" 전부다
        return _unavailable(static_outcome, type(error).__name__, enforce=enforce)

    if isinstance(thresholds, RiskBandThresholds):
        probability = score.probability
        if probability is None and len(score.probabilities) == 1:
            probability = next(iter(score.probabilities.values()))
        if probability is None:
            return _unavailable(static_outcome, "no_probability", enforce=enforce)
        return _single(static_outcome, score, probability, thresholds, enforce)
    return _per_question(static_outcome, score, thresholds, enforce)


def _unavailable(
    static_outcome: ApprovalPolicyOutcome, reason: str, *, enforce: bool
) -> BandedDecision:
    """대답하지 않았다 -- 좁힐 근거가 없으므로 R₀ 가 선다(D-L1)."""
    return BandedDecision(
        outcome=static_outcome,
        event={
            "kind": JEV_UNAVAILABLE,
            "reason": reason,
            "static_outcome": str(static_outcome),
            "enforced": enforce,
        },
    )


def _blocked(static_outcome: ApprovalPolicyOutcome, *, enforce: bool) -> BandedDecision:
    """막혔다 -- 중간대처럼 한 단계 좁힌다(D-L3).

    "애매하다"가 정보인 것처럼(§12.4) "막혔다"도 정보다: 요청에 WAF 가 공격
    페이로드로 보는 문자열이 들어 있었다. R₀ 로 폴백하면 그 문자열을 넣는
    것만으로 게이트가 열린다. 중간대 바닥(REQUIRE_APPROVAL)으로 좁히면 대면
    런은 사람에게 묻고, unattended 런은 기존 접기가 DENY 로 만든다 -- 규칙을
    새로 쓰지 않고 §12.4 의 표에 한 줄을 더하는 것이다.
    """
    narrowed = narrow(static_outcome, RiskBand.MID)
    return BandedDecision(
        outcome=narrowed if enforce else static_outcome,
        event={
            "kind": JEV_UNAVAILABLE,
            "reason": PROVIDER_BLOCKED,
            "blocked": True,
            "static_outcome": str(static_outcome),
            "would_be_outcome": str(narrowed),
            "enforced": enforce,
        },
    )


def _single(
    static_outcome: ApprovalPolicyOutcome,
    score: RiskScore,
    probability: float,
    thresholds: RiskBandThresholds,
    enforce: bool,
) -> BandedDecision:
    band = band_for(probability, thresholds)
    narrowed = narrow(static_outcome, band)
    return BandedDecision(
        outcome=narrowed if enforce else static_outcome,
        event={
            "kind": JEV_RISK_SCORED,
            "probability": probability,
            "band": str(band),
            "low_below": thresholds.low_below,
            "high_at_or_above": thresholds.high_at_or_above,
            "rubric_digest": score.rubric_digest,
            "model": score.model,
            "static_outcome": str(static_outcome),
            "would_be_outcome": str(narrowed),
            "enforced": enforce,
        },
    )


def _per_question(
    static_outcome: ApprovalPolicyOutcome,
    score: RiskScore,
    thresholds: Mapping[str, RiskBandThresholds],
    enforce: bool,
) -> BandedDecision:
    """쪼갠 루브릭(D-L2): 질문마다 제 경계로 밴딩하고, **가장 엄한 결과**를 취한다.

    확률을 하나로 합치지 않는다 -- max 도 noisy-OR 도 아니다. 합치는 규칙은
    그 자체가 새 매직넘버 후보이고(§9), 원장이 "왜 높았는가"를 다시 잃는다.
    대신 단조 축소를 질문마다 한 번씩 적용한다: 각 질문이 R₀ 를 좁힐 수 있고
    어느 것도 넓힐 수 없으므로, 여러 번 좁힌 결과도 결코 R₀ 보다 느슨하지 않다.

    대답이 질문 하나라도 빠지면 판정하지 않는다 -- 빠진 축을 LOW 로 읽으면
    그 축의 위험이 조용히 사라진다.
    """
    missing = [name for name in thresholds if name not in score.probabilities]
    if missing:
        return _unavailable(
            static_outcome, f"missing_questions:{','.join(missing)}", enforce=enforce
        )

    questions: list[dict[str, Any]] = []
    narrowed = static_outcome
    driver: dict[str, Any] | None = None
    for name, bounds in thresholds.items():
        probability = score.probabilities[name]
        band = band_for(probability, bounds)
        entry = {
            "name": name,
            "probability": probability,
            "band": str(band),
            "low_below": bounds.low_below,
            "high_at_or_above": bounds.high_at_or_above,
        }
        questions.append(entry)
        # 가장 높은 밴드의 질문이 "왜"다. 결과(outcome)로 고르지 않는다 -- R₀ 가
        # 이미 엄하면 결과는 질문을 가르지 못하는데, 원장은 여전히 무엇이 가장
        # 경고했는지 말해야 한다. 동률은 먼저 온 질문(루브릭 순서)이 가진다.
        if driver is None or _BAND_SEVERITY[band] > _BAND_SEVERITY[RiskBand(driver["band"])]:
            driver = entry
        narrowed = narrow(narrowed, band)

    assert driver is not None  # thresholds 는 비어 있지 않다(조립이 막는다)
    return BandedDecision(
        outcome=narrowed if enforce else static_outcome,
        event={
            "kind": JEV_RISK_SCORED,
            # 결과를 정한 질문의 값을 위로 올린다. 질문 하나짜리 이벤트를
            # 읽던 쪽(프론트 배지, 리뷰 스크립트)이 그대로 읽는다.
            "probability": driver["probability"],
            "band": driver["band"],
            "low_below": driver["low_below"],
            "high_at_or_above": driver["high_at_or_above"],
            "driver": driver["name"],
            "questions": questions,
            "rubric_digest": score.rubric_digest,
            "model": score.model,
            "static_outcome": str(static_outcome),
            "would_be_outcome": str(narrowed),
            "enforced": enforce,
        },
    )


async def evaluate_approval_with_jev(
    call: "ValidatedToolCall",
    gate: ApprovalGate | None = None,
    *,
    scorer: ToolRiskScorer,
    thresholds: "RiskBandThresholds | Mapping[str, RiskBandThresholds]",
    enforce: bool,
    static_evaluator: "Callable[[ValidatedToolCall, ApprovalGate], ApprovalPolicyOutcome]" = None,  # type: ignore[assignment]
) -> BandedDecision:
    """정적 정책 → Jev 밴딩 → unattended 접기. **이 순서가 계약이다.**

    `evaluate_approval` 과 같은 자리를 지나되, 접기 앞에 밴딩 한 단계가
    끼어든다. 접기를 여기서 다시 구현하지 않고 `fold_for_unattended` 를
    부르는 것이 요점이다 -- 규칙 사본이 둘이 되면 고침은 한쪽에만 도착한다.

    정적 판정이 터지면 `evaluate_approval` 과 똑같이 DENY 로 닫는다. Jev 가
    터지는 것과 정적 정책이 터지는 것은 **다른 사건**이다: 앞은 축소할 근거가
    없어 R₀ 가 서고, 뒤는 R₀ 자체가 없다.

    `static_evaluator` 는 R₀ 를 내는 함수다. durable 루프가 **주입된 평가기**를
    쓰기 때문에 열어 둔다 -- 이 인자가 없으면 루프가 순서를 자기 쪽에 다시
    구현하게 되고, 그러면 D-L1 의 순서 계약을 검사하는 테스트가 프로덕션이
    아니라 사본을 검사하게 된다.
    """
    resolved = gate or ApprovalGate()
    evaluate_static = static_evaluator or evaluate_static_approval
    try:
        static_outcome = evaluate_static(call, resolved)
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
    if event is not None:
        event = dict(event)
        # 원장이 "누가 좁혔는가"를 말하게 한다. 접기는 Jev 없이도 일어나므로,
        # 접힌 값만 남기면 unattended 런의 DENY 가 Jev 의 판정처럼 읽힌다.
        event["unattended"] = resolved.unattended
    if event is not None and "would_be_outcome" in event:
        event["banded_outcome"] = event["would_be_outcome"]
        event["would_be_outcome"] = str(
            fold_for_unattended(
                ApprovalPolicyOutcome(event["would_be_outcome"]), resolved
            )
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
