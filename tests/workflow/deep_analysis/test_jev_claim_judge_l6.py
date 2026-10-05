"""L6 -- 심층분석 클레임 판정을 Jev 로 (DECISIONS D99, 로드맵 §12.5).

실호출은 없다(§12.2 ①). Jev 응답은 진짜 SDK 타입으로 만들고, LLM 판정자는
`test_agentic_grader.py` 의 가짜와 같은 모양이다.

무는지 확인하는 것: 단조 축소가 판정에도 걸린다(애매함·WAF 는 반려), Jev 가
대답하지 않으면 LLM 으로 폴백하되 **그 사실이 diagnostics 에 남는다**, 계산
클레임은 Jev 로 가지 않는다, 티어링은 하나다.
"""

from __future__ import annotations

import pytest
from typesafe_sdk import SystemOneResponse

from neos.config.schema import JevConfig
from neos.jev.assembly import MisconfiguredJev, build_claim_judge
from neos.jev.claim_judge import TypeSafeClaimJudge
from neos.jev.rubric import load_rubric
from neos.workflow.deep_analysis.graders.agentic import (
    AgenticGrader,
    ComputedJudgeContext,
)
from neos.workflow.deep_analysis.models import ComputedEvidence, ProposedClaim, ProposedEvidence

pytestmark = pytest.mark.no_db

PROBS = {"SUPPORTS": 0.1, "PARTIAL": 0.1, "UNRELATED": 0.1, "CONTRADICTS": 0.7}


def _response(choice: str, confidence: float) -> SystemOneResponse:
    return SystemOneResponse.model_validate(
        {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 11, "output_tokens": 2},
            "answers": {
                "label": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": confidence,
                    "probabilities": PROBS,
                }
            },
        }
    )


class JevClient:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls = 0

    async def system_one(self, state, questions, **kwargs):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reply


class LlmJudge:
    """`test_agentic_grader.FakeJudge` 와 같은 모양."""

    def __init__(self, label: str) -> None:
        self._label = label
        self.messages = self
        self.calls = 0

    async def create(self, **kw):
        self.calls += 1
        payload = '{"label": "%s", "rationale": "r"}' % self._label

        class U:
            input_tokens = 5
            output_tokens = 3

        class B:
            type = "text"
            text = payload

        class R:
            content = [B()]
            usage = U()
            model = kw["model"]

        return R()


class Blocked(Exception):
    """TypeSafe 앞단 WAF 의 403 모양(`is_provider_block`)."""

    status = 403
    request_id = None
    body = "<html><body>blocked</body></html>"


def _judge(client: JevClient) -> TypeSafeClaimJudge:
    return TypeSafeClaimJudge(
        client=client,
        model="jev-1.13.0",
        rubric=load_rubric("claim_judgement"),
        question="label",
        timeout_sec=5.0,
    )


def _grader(jev: JevClient, llm: LlmJudge, *, min_confidence: float = 0.5, **kw):
    options = dict(threshold=0.0, sample_rate=1.0)
    options.update(kw)
    return AgenticGrader(
        judge_model="claude-j",
        max_output_tokens=800,
        llm_client=llm,
        jev_judge=_judge(jev),
        jev_min_confidence=min_confidence,
        **options,
    )


def _claim(conf: float = 0.6) -> ProposedClaim:
    return ProposedClaim(
        text="MoE lowers cost",
        confidence=conf,
        evidence=[ProposedEvidence("http://x", "cost drops 40%", "hh")],
    )


@pytest.mark.parametrize(
    "label,ok,code",
    [
        ("SUPPORTS", True, ""),
        ("PARTIAL", False, "E_OVERCLAIM"),
        ("UNRELATED", False, "E_UNSUPPORTED"),
        ("CONTRADICTS", False, "E_CONTRADICTED"),
    ],
)
async def test_jev_choice_becomes_the_verdict_and_the_llm_is_not_called(label, ok, code):
    jev, llm = JevClient(_response(label, 0.9)), LlmJudge("SUPPORTS")
    verdict = await _grader(jev, llm).grade(_claim(), value_est=1.0)
    assert (verdict.ok, verdict.code, verdict.label) == (ok, code, label)
    assert jev.calls == 1 and llm.calls == 0
    assert verdict.tokens_spent == 0 == verdict.diagnostics["judge_tokens"]


async def test_every_jev_verdict_carries_what_s13_needs():
    jev = JevClient(_response("SUPPORTS", 0.9))
    verdict = await _grader(jev, LlmJudge("SUPPORTS")).grade(_claim(), value_est=1.0)
    d = verdict.diagnostics
    assert d["judge_backend"] == "jev"
    assert d["jev_model"] == "jev-1.13.0"
    assert d["jev_rubric_digest"] == load_rubric("claim_judgement").digest
    assert d["jev_min_confidence"] == 0.5
    assert d["jev_confidence"] == 0.9 and d["jev_probabilities"] == PROBS
    assert d["jev_uid"].startswith(load_rubric("claim_judgement").digest)


@pytest.mark.parametrize("mandatory", [True, False])
async def test_an_uncertain_answer_narrows_to_rejection(mandatory):
    """애매함은 정보다 -- SUPPORTS 라도 확신이 경계 밑이면 반려한다."""
    jev, llm = JevClient(_response("SUPPORTS", 0.49)), LlmJudge("SUPPORTS")
    grader = _grader(
        jev, llm, threshold=0.35 if not mandatory else 0.0, sample_rate=1.0
    )
    verdict = await grader.grade(_claim(conf=0.1 if not mandatory else 0.6), value_est=0.1)
    assert verdict.ok is False and verdict.code == "E_UNSUPPORTED"
    assert verdict.detail == ("jev_uncertain_mandatory" if mandatory else "jev_uncertain")
    assert llm.calls == 0


async def test_a_waf_block_narrows_and_does_not_fall_back():
    """D-L3: 막는 문자열은 증거에 공격자가 넣을 수 있다 -- 폴백으로 열지 않는다."""
    jev, llm = JevClient(error=Blocked()), LlmJudge("SUPPORTS")
    verdict = await _grader(jev, llm).grade(_claim(), value_est=1.0)
    assert verdict.ok is False and verdict.detail == "jev_provider_blocked"
    assert verdict.diagnostics["jev_unavailable"] == "provider_blocked"
    assert llm.calls == 0


async def test_an_unanswered_call_falls_back_to_the_llm_and_says_so():
    jev, llm = JevClient(error=TimeoutError()), LlmJudge("CONTRADICTS")
    verdict = await _grader(jev, llm).grade(_claim(), value_est=1.0)
    assert verdict.label == "CONTRADICTS" and llm.calls == 1
    assert verdict.diagnostics["judge_backend"] == "llm_fallback"
    assert verdict.diagnostics["jev_unavailable"] == "TimeoutError"
    # 폴백한 판정의 토큰은 LLM 이 쓴 그대로다.
    assert verdict.tokens_spent == 8 == verdict.diagnostics["judge_tokens"]


async def test_an_unsampled_claim_calls_neither_judge():
    jev, llm = JevClient(_response("SUPPORTS", 0.9)), LlmJudge("SUPPORTS")
    grader = _grader(jev, llm, threshold=0.35, sample_rate=0.0, sampler=lambda: 0.99)
    verdict = await grader.grade(_claim(conf=0.01), value_est=0.01)
    assert verdict.ok is True and verdict.label is None
    assert jev.calls == 0 and llm.calls == 0


async def test_computed_claims_stay_with_the_llm_judge():
    """claim_judgement 루브릭은 계산 클레임을 다루지 않는다(GRADE1)."""
    jev, llm = JevClient(_response("SUPPORTS", 0.9)), LlmJudge("SUPPORTS")
    claim = ProposedClaim(
        text="A is 2x B",
        confidence=0.6,
        kind="computed",
        computation=ComputedEvidence(
            script_ref="sandbox-script://s",
            inputs=["r"],
            output_digest="o",
            claimed_value="2",
            premises=["c1"],
        ),
    )
    context = ComputedJudgeContext(
        question_text="q", computed_value="2", premises=(("A=2", ("A is 2",)),)
    )
    verdict = await _grader(jev, llm).grade(claim, value_est=1.0, computed=context)
    assert verdict.label == "SUPPORTS" and jev.calls == 0 and llm.calls == 1
    assert "judge_backend" not in verdict.diagnostics


def test_judge_and_boundary_come_together():
    with pytest.raises(ValueError):
        AgenticGrader(
            judge_model="j",
            threshold=0.0,
            sample_rate=1.0,
            max_output_tokens=8,
            jev_judge=_judge(JevClient()),
        )


def test_the_judge_cannot_be_enabled_without_a_boundary():
    with pytest.raises(ValueError, match="judge_min_confidence"):
        JevConfig(enabled=True, model="jev-1.13.0", judge_enabled=True)
    with pytest.raises(ValueError, match="jev.enabled"):
        JevConfig(judge_enabled=True, judge_min_confidence=0.5)


def test_assembly_is_the_only_place_that_decides():
    assert build_claim_judge(JevConfig()) is None
    on = JevConfig(
        enabled=True, model="jev-1.13.0", judge_enabled=True, judge_min_confidence=0.5
    )
    with pytest.raises(MisconfiguredJev, match="TYPESAFE_API_KEY"):
        build_claim_judge(on, api_key="")
    judge = build_claim_judge(on, api_key="k", client=JevClient())
    assert isinstance(judge, TypeSafeClaimJudge)
    assert judge.labels == ("SUPPORTS", "PARTIAL", "UNRELATED", "CONTRADICTS")


# -- 원장까지 도착하는가 (D102) ------------------------------------------------
#
# 위 테스트들은 `Verdict.diagnostics` 까지만 봤다. 원장의 `claim_graded` 는
# `Ledger._claim_graded_payload` 의 화이트리스트를 지나며, 그것이 Jev 필드를 몰라서
# 표본 #23 의 원장에 판정자가 하나도 남지 않았다. 여기서는 **원장이 쓰는 payload** 를 본다.


async def test_a_jev_verdict_reaches_the_ledger_payload():
    import json

    from neos.workflow.deep_analysis.ledger import Ledger

    verdict = await _grader(JevClient(_response("SUPPORTS", 0.9)), LlmJudge("SUPPORTS")).grade(
        _claim(), value_est=1.0
    )
    payload = Ledger._claim_graded_payload("c1", "verified", verdict)
    json.dumps(payload)  # 진짜 원장은 JSON 만 받는다
    assert payload["judge_backend"] == "jev"
    assert payload["jev_model"] == "jev-1.13.0"
    assert payload["jev_rubric_digest"] == load_rubric("claim_judgement").digest
    assert payload["jev_min_confidence"] == 0.5 and payload["jev_confidence"] == 0.9
    assert payload["jev_probabilities"] == PROBS and payload["jev_choice"] == "SUPPORTS"


async def test_the_ledger_tells_an_uncertain_rejection_from_a_waf_block():
    from neos.workflow.deep_analysis.ledger import Ledger

    uncertain = await _grader(JevClient(_response("SUPPORTS", 0.1)), LlmJudge("SUPPORTS")).grade(
        _claim(), value_est=1.0
    )
    blocked = await _grader(JevClient(error=Blocked()), LlmJudge("SUPPORTS")).grade(
        _claim(), value_est=1.0
    )
    assert Ledger._claim_graded_payload("c", "rejected", uncertain)["judge_detail"] == (
        "jev_uncertain_mandatory"
    )
    b = Ledger._claim_graded_payload("c", "rejected", blocked)
    assert b["judge_detail"] == "jev_provider_blocked" and b["jev_unavailable"] == "provider_blocked"


async def test_a_fallback_is_visible_in_the_ledger():
    from neos.workflow.deep_analysis.ledger import Ledger

    verdict = await _grader(JevClient(error=TimeoutError()), LlmJudge("SUPPORTS")).grade(
        _claim(), value_est=1.0
    )
    payload = Ledger._claim_graded_payload("c", "verified", verdict)
    assert payload["judge_backend"] == "llm_fallback"
    assert payload["jev_unavailable"] == "TimeoutError"


async def test_with_jev_off_the_ledger_payload_gains_no_key():
    """L6 이 꺼진 런의 원장은 바이트가 같아야 한다 -- 새 키가 하나도 없다."""
    from neos.workflow.deep_analysis.ledger import Ledger

    llm_only = AgenticGrader(
        judge_model="claude-j",
        threshold=0.0,
        sample_rate=1.0,
        max_output_tokens=800,
        llm_client=LlmJudge("SUPPORTS"),
    )
    payload = Ledger._claim_graded_payload("c", "verified", await llm_only.grade(_claim(), 1.0))
    assert not [key for key in payload if key.startswith(("jev_", "judge_"))]
