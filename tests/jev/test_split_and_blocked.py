"""D-L2(쪼갠 루브릭)와 D-L3(WAF 차단) -- 로드맵 §12.11.

D-L2: 질문마다 제 경계로 밴딩하고 가장 엄한 결과를 취한다. 확률을 합치지 않는다.
D-L3: 프로바이더 앞단이 막은 호출은 R₀ 로 폴백하지 않고 한 단계 좁힌다. 막을 수
있는 문자열을 도구 입력에 넣는 것은 공격자가 할 수 있기 때문이다.
"""

from __future__ import annotations

import itertools
import json
from types import SimpleNamespace

import httpx
import pytest

from neos.coding.domain.approvals import ApprovalGate, ApprovalPolicyOutcome
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall
from neos.jev.banding import RiskBandThresholds, is_at_least_as_strict
from neos.jev.gate import (
    JEV_UNAVAILABLE,
    PROVIDER_BLOCKED,
    JevProviderBlocked,
    RiskScore,
    apply_tool_risk_banding,
    evaluate_approval_with_jev,
)
from neos.jev.rubric import load_rubric
from neos.jev.scorer import TypeSafeToolRiskScorer, is_provider_block

pytestmark = pytest.mark.no_db

BOUNDS = RiskBandThresholds(low_below=0.3, high_at_or_above=0.8)
SPLIT = {"irreversible": BOUNDS, "exfiltration": BOUNDS}
OUTCOMES = list(ApprovalPolicyOutcome)


class SplitScorer:
    def __init__(self, **probabilities: float) -> None:
        self._probabilities = probabilities

    async def score_tool_risk(self, state: object) -> RiskScore:
        del state
        return RiskScore(
            probability=None,
            model="jev-1.13.0",
            rubric_digest="d" * 64,
            probabilities=self._probabilities,
        )


class BlockedScorer:
    async def score_tool_risk(self, state: object) -> RiskScore:
        del state
        raise JevProviderBlocked("403")


async def banded(static: ApprovalPolicyOutcome, scorer, *, enforce: bool = True):
    return await apply_tool_risk_banding(
        static, scorer=scorer, state={"tool": "x"}, thresholds=SPLIT, enforce=enforce
    )


# ── D-L2 ────────────────────────────────────────────────────────────────────


async def test_the_credential_read_the_single_question_missed_is_caught() -> None:
    """§12.11 ①: 단일 질문은 `cat ~/.aws/credentials` 에 0.10 을 줬다."""
    decision = await banded(
        ApprovalPolicyOutcome.ALLOW, SplitScorer(irreversible=0.03, exfiltration=0.61)
    )
    assert decision.outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert decision.event["driver"] == "exfiltration"
    assert decision.event["probability"] == 0.61
    assert decision.event["band"] == "mid"


async def test_the_strictest_question_wins() -> None:
    decision = await banded(
        ApprovalPolicyOutcome.ALLOW, SplitScorer(irreversible=0.5, exfiltration=0.97)
    )
    assert decision.outcome is ApprovalPolicyOutcome.DENY
    assert decision.event["driver"] == "exfiltration"


async def test_every_question_is_recorded_not_just_the_driver() -> None:
    """원장이 "왜"를 말하려면 가장 높은 것만이 아니라 전부가 있어야 한다."""
    decision = await banded(
        ApprovalPolicyOutcome.ALLOW, SplitScorer(irreversible=0.75, exfiltration=0.02)
    )
    by_name = {q["name"]: q for q in decision.event["questions"]}
    assert by_name["irreversible"]["band"] == "mid"
    assert by_name["exfiltration"]["band"] == "low"
    assert by_name["exfiltration"]["high_at_or_above"] == 0.8
    json.dumps(decision.event)  # payload 는 원장에 그대로 들어간다(§12.8 ③)


async def test_a_tie_goes_to_the_first_question_in_rubric_order() -> None:
    decision = await banded(
        ApprovalPolicyOutcome.ALLOW, SplitScorer(irreversible=0.5, exfiltration=0.5)
    )
    assert decision.event["driver"] == "irreversible"


async def test_a_missing_question_is_not_read_as_low() -> None:
    """빠진 축을 LOW 로 읽으면 그 축의 위험이 조용히 사라진다."""
    decision = await banded(ApprovalPolicyOutcome.ALLOW, SplitScorer(irreversible=0.1))
    assert decision.event["kind"] == JEV_UNAVAILABLE
    assert decision.event["reason"] == "missing_questions:exfiltration"
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW


@pytest.mark.parametrize(
    ("static", "p_irr", "p_exf"),
    list(
        itertools.product(
            [ApprovalPolicyOutcome.ALLOW, ApprovalPolicyOutcome.REQUIRE_APPROVAL],
            [0.0, 0.5, 0.9],
            [0.0, 0.5, 0.9],
        )
    ),
)
async def test_splitting_never_loosens_r0(static, p_irr, p_exf) -> None:
    """S11 을 질문마다: 몇 번을 좁혀도 R₀ 보다 느슨해지지 않는다."""
    decision = await banded(static, SplitScorer(irreversible=p_irr, exfiltration=p_exf))
    assert is_at_least_as_strict(decision.outcome, static)


async def test_a_shadow_split_changes_nothing() -> None:
    decision = await banded(
        ApprovalPolicyOutcome.ALLOW,
        SplitScorer(irreversible=0.9, exfiltration=0.9),
        enforce=False,
    )
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW
    assert decision.event["would_be_outcome"] == "deny"


# ── D-L3 ────────────────────────────────────────────────────────────────────


async def test_a_blocked_call_narrows_one_step_when_enforced() -> None:
    """R₀ 로 폴백하면 막히는 문자열을 넣는 것만으로 게이트가 열린다."""
    decision = await banded(ApprovalPolicyOutcome.ALLOW, BlockedScorer())
    assert decision.outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert decision.event["kind"] == JEV_UNAVAILABLE
    assert decision.event["reason"] == PROVIDER_BLOCKED
    assert decision.event["blocked"] is True


async def test_a_blocked_call_in_shadow_only_records() -> None:
    decision = await banded(ApprovalPolicyOutcome.ALLOW, BlockedScorer(), enforce=False)
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW
    assert decision.event["would_be_outcome"] == "require_approval"


async def test_an_unattended_blocked_call_is_denied_by_the_existing_fold() -> None:
    """새 규칙을 쓰지 않는다 -- 중간대 바닥으로 좁히면 기존 접기가 DENY 로 만든다."""
    decision = await evaluate_approval_with_jev(
        ValidatedToolCall(name="read_file", input={"path": "a"}, risk=ToolRisk.READ_ONLY),
        ApprovalGate(unattended=True),
        scorer=BlockedScorer(),
        thresholds=SPLIT,
        enforce=True,
    )
    assert decision.outcome is ApprovalPolicyOutcome.DENY
    assert decision.event["banded_outcome"] == "require_approval"
    assert decision.event["would_be_outcome"] == "deny"


async def test_an_ordinary_failure_still_falls_back_to_r0() -> None:
    """D-L1 은 그대로다: 타임아웃은 좁힐 근거가 없다."""

    class Timeout:
        async def score_tool_risk(self, state: object) -> RiskScore:
            raise TimeoutError

    decision = await banded(ApprovalPolicyOutcome.ALLOW, Timeout())
    assert decision.outcome is ApprovalPolicyOutcome.ALLOW
    assert decision.event["reason"] == "TimeoutError"
    assert "blocked" not in decision.event


# ── 분류: WAF 403 vs 서버가 거절한 403 ─────────────────────────────────────


def sdk_error(status: int, body, *, request_id: str | None):
    from typesafe_sdk._core.errors import (
        TypeSafeAuthenticationError,
        TypeSafePermissionDeniedError,
    )

    headers = httpx.Headers({"x-typesafe-request-id": request_id} if request_id else {})
    cls = TypeSafePermissionDeniedError if status == 403 else TypeSafeAuthenticationError
    return cls(status, body, headers)


CLOUDFLARE = "<!DOCTYPE html> <!--[if lt IE 7]> <html class='no-js'> Attention Required!"


def test_a_cloudflare_403_is_a_block() -> None:
    assert is_provider_block(sdk_error(403, CLOUDFLARE, request_id=None))


def test_a_403_that_reached_the_server_is_not_a_block() -> None:
    """잘못된 키를 "차단"으로 읽으면 키를 잃은 배포가 모든 호출에 승인을 요구한다."""
    assert not is_provider_block(
        sdk_error(403, {"detail": "forbidden"}, request_id="req_1")
    )


def test_an_html_403_with_a_request_id_is_not_a_block() -> None:
    """두 신호를 다 요구한다 -- 하나만 보면 한쪽 오분류가 생긴다."""
    assert not is_provider_block(sdk_error(403, CLOUDFLARE, request_id="req_1"))


def test_a_401_is_never_a_block() -> None:
    assert not is_provider_block(sdk_error(401, CLOUDFLARE, request_id=None))


async def test_the_scorer_turns_a_waf_403_into_a_block() -> None:
    class WafClient:
        async def system_one(self, state, questions, **kwargs):
            raise sdk_error(403, CLOUDFLARE, request_id=None)

    scorer = TypeSafeToolRiskScorer(
        client=WafClient(),
        model="jev-1.13.0",
        rubric=load_rubric("tool_risk_split"),
        questions=("irreversible", "exfiltration"),
        timeout_sec=5,
    )
    with pytest.raises(JevProviderBlocked):
        await scorer.score_tool_risk({"tool": "x"})


async def test_the_split_scorer_returns_every_question() -> None:
    class Client:
        async def system_one(self, state, questions, **kwargs):
            assert set(questions) == {"irreversible", "exfiltration"}
            return SimpleNamespace(
                model="jev-1.13.0",
                nouls={
                    "irreversible": SimpleNamespace(noul=0.2),
                    "exfiltration": SimpleNamespace(noul=0.7),
                },
            )

    scorer = TypeSafeToolRiskScorer(
        client=Client(),
        model="jev-1.13.0",
        rubric=load_rubric("tool_risk_split"),
        questions=("irreversible", "exfiltration"),
        timeout_sec=5,
    )
    score = await scorer.score_tool_risk({"tool": "x"})
    assert score.probability is None
    assert dict(score.probabilities) == {"irreversible": 0.2, "exfiltration": 0.7}


def test_the_scorer_takes_one_question_or_many_not_both() -> None:
    with pytest.raises(ValueError):
        TypeSafeToolRiskScorer(
            client=object(),
            model="jev-1.13.0",
            rubric=load_rubric("tool_risk_split"),
            question="irreversible",
            questions=("irreversible",),
            timeout_sec=5,
        )
