"""GRADE1: the judge reads a computed claim through its value and premises.

A computed claim carries no excerpts. Handed to the quote prompt the judge saw
"(증거 없음)", so a claim that had passed re-execution could only come back
UNRELATED. Contract §5 gives the judge a narrower question for these; this
file pins that it is asked, with the material it needs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.graders.agentic import (
    AgenticGrader,
    ComputedJudgeContext,
)
from neos.workflow.deep_analysis.models import (
    ComputedEvidence,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.prompt_loader import render

pytestmark = pytest.mark.no_db


class RecordingJudge:
    def __init__(self, label: str = "SUPPORTS") -> None:
        self._label = label
        self.messages = self
        self.requests: list[dict] = []

    async def create(self, **kw):
        self.requests.append(kw)
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

    def sent(self) -> str:
        return json.dumps(self.requests, ensure_ascii=False, default=str)


def _grader(judge) -> AgenticGrader:
    return AgenticGrader(
        judge_model="claude-j",  # the Anthropic path is what `RecordingJudge` fakes
        threshold=0.0,  # everything is mandatory: the judge is always asked
        sample_rate=0.0,
        max_output_tokens=800,
        llm_client=judge,
    )


def _computed_claim(text: str = "A 의 매출은 B 의 2.3배다") -> ProposedClaim:
    return ProposedClaim(
        text=text,
        confidence=0.5,
        kind="computed",
        computation=ComputedEvidence(
            script_ref="sha_script",
            inputs=["sha_a", "sha_b"],
            premises=["c_a", "c_b"],
            runtime={},
            output_digest="d",
            claimed_value="2.3",
        ),
    )


_CONTEXT = ComputedJudgeContext(
    question_text="A 와 B 중 어느 쪽 매출이 큰가",
    computed_value="2.3",
    premises=(
        ("A 의 2025 매출은 46억 달러다", ("revenue was $4.6 billion",)),
        ("B 의 2025 매출은 20억 달러다", ("revenue of $2.0 billion",)),
    ),
)


@pytest.mark.asyncio
async def test_a_computed_claim_is_judged_on_its_value_and_premises() -> None:
    """Mutation: send computed claims down the quote branch -> "(증거 없음)"."""
    judge = RecordingJudge("SUPPORTS")

    verdict = await _grader(judge).grade(_computed_claim(), 1.0, computed=_CONTEXT)

    assert verdict.ok is True
    sent = judge.sent()
    assert "(증거 없음)" not in sent
    assert "A 와 B 중 어느 쪽 매출이 큰가" in sent
    assert "검증된 계산 값: 2.3" in sent
    assert "<evidence>revenue was $4.6 billion</evidence>" in sent
    assert "<premise>B 의 2025 매출은 20억 달러다</premise>" in sent


@pytest.mark.asyncio
async def test_an_overreaching_computed_claim_can_still_be_rejected() -> None:
    """The judge is still a judge: PARTIAL maps to E_OVERCLAIM as for quotes."""
    judge = RecordingJudge("PARTIAL")

    verdict = await _grader(judge).grade(
        _computed_claim("A 의 매출은 B 의 2.3배이므로 A 가 시장을 지배한다"),
        1.0,
        computed=_CONTEXT,
    )

    assert verdict.ok is False
    assert verdict.code == "E_OVERCLAIM"


@pytest.mark.asyncio
async def test_a_computed_claim_without_context_is_never_judged_blind() -> None:
    """Mutation: fall through to the quote prompt when context is missing."""
    judge = RecordingJudge("SUPPORTS")

    verdict = await _grader(judge).grade(_computed_claim(), 1.0)

    assert judge.requests == []
    assert verdict.ok is False
    assert verdict.detail == "computed_context_missing"
    assert verdict.tokens_spent == 0


@pytest.mark.asyncio
async def test_the_quote_prompt_is_byte_identical() -> None:
    """Flag off there are no computed claims; what quotes see must not move."""
    judge = RecordingJudge("SUPPORTS")
    claim = ProposedClaim(
        text="MoE lowers cost",
        confidence=0.6,
        evidence=[ProposedEvidence("http://x", "cost drops 40%", "hh")],
    )

    await _grader(judge).grade(claim, 1.0)

    expected = render(
        "judge",
        claim_text="MoE lowers cost",
        evidence_block="<evidence>cost drops 40%</evidence>",
    )
    assert json.dumps(expected, ensure_ascii=False)[1:-1] in judge.sent()


class _Ledger:
    async def get_question(self, question_id):
        assert question_id == "q1"
        return SimpleNamespace(text="A 와 B 중 어느 쪽 매출이 큰가")

    async def get_claim(self, claim_id):
        return SimpleNamespace(
            text={"c_a": "A 의 2025 매출은 46억 달러다", "c_b": "B 의 2025 매출은 20억 달러다"}[
                claim_id
            ]
        )

    async def claim_evidence(self, claim_id):
        excerpt = {
            "c_a": "revenue was $4.6 billion",
            "c_b": "revenue of $2.0 billion",
        }[claim_id]
        return [SimpleNamespace(excerpt=excerpt)]


class _PassingDeterministic:
    async def grade(self, claim):
        return Verdict(ok=True, diagnostics={"deterministic": "passed"})


class _RecordingAgentic:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def grade(self, claim, value_est, **kwargs):
        self.calls.append(kwargs)
        return Verdict(ok=True, label="SUPPORTS", diagnostics={})


def _orchestrator_stub(agentic):
    stub = SimpleNamespace(
        ledger=_Ledger(), grader=_PassingDeterministic(), agentic_grader=agentic
    )
    stub._computed_judge_context = (
        lambda claim, question_id: Orchestrator._computed_judge_context(
            stub, claim, question_id
        )
    )
    return stub


@pytest.mark.asyncio
async def test_the_orchestrator_hands_the_judge_the_ledgers_premises() -> None:
    """The context comes from the ledger: question text and premise excerpts.

    Mutation: build the context without the question, or skip the premises'
    evidence -> the context differs. Also pins the routing: a quote claim gets
    no `computed` keyword at all. This calls `_grade` directly; it does not
    catch a caller that stops passing `question_id`.
    """
    agentic = _RecordingAgentic()
    stub = _orchestrator_stub(agentic)

    await Orchestrator._grade(stub, _computed_claim(), 1.0, "q1")
    await Orchestrator._grade(
        stub,
        ProposedClaim(
            text="t",
            confidence=0.5,
            evidence=[ProposedEvidence("http://x", "e", "r")],
        ),
        1.0,
        "q1",
    )

    computed_call, quote_call = agentic.calls
    assert computed_call["computed"] == _CONTEXT
    assert quote_call == {}


def test_the_stored_computation_round_trips() -> None:
    from neos.workflow.deep_analysis.ledger import _computation_json, stored_computation

    claim = _computed_claim()

    assert stored_computation(_computation_json(claim)) == claim.computation
    assert stored_computation(None) is None


@pytest.mark.asyncio
async def test_a_repaired_computed_claim_is_regraded_as_computed() -> None:
    """GRADE1 follow-up: a repair pushes a claim back to `pending`.

    Now that the judge can say PARTIAL on a computed claim, weakening and
    resubmitting is a live path. The regrade rebuilt the claim from the row
    without `kind`, so it went through the quote tier with no excerpts.
    Mutation: drop `kind=`/`computation=` from `_regrade_pending`.
    """
    from neos.workflow.deep_analysis.ledger import _computation_json

    graded: list[ProposedClaim] = []
    stored = SimpleNamespace(
        id="c9",
        text="A 의 매출은 B 의 2.3배다",
        confidence=0.5,
        kind="computed",
        computation=_computation_json(_computed_claim()),
    )

    class Ledger:
        async def pending_claims(self, question_id):
            return [(stored, [])]

        async def regrade_claim(self, question_id, claim_id, verdict):
            return None

    async def grade(claim, value_est, question_id=None):
        graded.append(claim)
        return Verdict(ok=True)

    stub = SimpleNamespace(ledger=Ledger(), _grade=grade)
    await Orchestrator._regrade_pending(stub, "q1", 1.0)

    [claim] = graded
    assert claim.kind == "computed"
    assert claim.computation == _computed_claim().computation
