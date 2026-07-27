import math

import pytest

from neos.workflow.deep_analysis.discard_recall import score_discards
from neos.workflow.deep_analysis.graders.agentic import AgenticGrader
from neos.workflow.deep_analysis.models import ProposedClaim, ProposedEvidence


pytestmark = pytest.mark.no_db


def _event(text, verified):
    return {
        "text": text,
        "confidence": 0.6,
        "value_est": 1.0,
        "evidence": [
            {
                "source_url": "https://example.com/source",
                "excerpt": "Direct evidence.",
                "raw_ref": "0123456789abcdef",
            }
        ],
        "_verified": verified,
    }


async def _grade_fn(claim, value_est, verified_lookup):
    return verified_lookup[claim.text]


async def test_score_discards_counts_verified_and_reports_interval():
    events = [_event("a", True), _event("b", False), _event("c", False)]
    lookup = {"a": True, "b": False, "c": False}

    result = await score_discards(
        events,
        grade_fn=lambda claim, value_est: _grade_fn(claim, value_est, lookup),
        wilson_z=1.96,
        safe_upper=0.10,
        over_discard_lower=0.40,
    )

    assert result["total_discarded"] == 3
    assert result["verified"] == 1
    assert result["false_discard_rate"] == pytest.approx(1 / 3)
    assert result["verdict"] == "inconclusive"
    assert result["malformed"] == 0


async def test_score_discards_counts_malformed_events_without_grading():
    result = await score_discards(
        [{"text": "", "confidence": 0.6, "evidence": []}],
        grade_fn=lambda claim, value_est: _grade_fn(claim, value_est, {}),
        wilson_z=1.96,
        safe_upper=0.10,
        over_discard_lower=0.40,
    )

    assert result["total_discarded"] == 0
    assert result["malformed"] == 1


async def test_score_discards_empty_input_is_inconclusive():
    result = await score_discards(
        [],
        grade_fn=lambda claim, value_est: _grade_fn(claim, value_est, {}),
        wilson_z=1.96,
        safe_upper=0.10,
        over_discard_lower=0.40,
    )

    assert result["total_discarded"] == 0
    assert result["verdict"] == "inconclusive"


class _FakeJudge:
    """Stands in for the Anthropic client so no real LLM call happens."""

    def __init__(self, label: str) -> None:
        self._label = label
        self.messages = self
        self.calls = 0

    async def create(self, **kw):
        self.calls += 1
        payload = '{"label": "%s", "rationale": "r"}' % self._label

        class _Usage:
            input_tokens = 5
            output_tokens = 3

        class _Block:
            type = "text"
            text = payload

        class _Response:
            content = [_Block()]
            usage = _Usage()
            model = kw["model"]

        return _Response()


def _non_mandatory_claim() -> ProposedClaim:
    # value_est(0.1) * confidence(0.1) = 0.01, well under the 0.35
    # threshold used below, so this claim is non-mandatory and would be
    # subject to sampling if the gate were active.
    return ProposedClaim(
        text="non-mandatory claim",
        confidence=0.1,
        evidence=[ProposedEvidence("http://x", "some evidence", "ref")],
    )


async def test_sample_rate_one_disables_the_agentic_sampling_gate():
    """The script's `_graders` builds AgenticGrader with sample_rate=1.0
    specifically to defeat the sampling gate inside grade() (agentic.py
    :71-78), which otherwise returns ok=True ("verified") for claims it
    never actually judged. This proves sample_rate=1.0 makes a
    non-mandatory, low-value claim reach the judge instead of being
    silently waved through as "skipped".
    """
    # The largest value a real sampler (random.random(), range [0, 1)) can
    # ever produce -- the most adversarial case for the gate.
    highest_possible_sample = math.nextafter(1.0, 0.0)
    assert highest_possible_sample < 1.0

    judge = _FakeJudge("SUPPORTS")
    grader = AgenticGrader(
        judge_model="claude-j",
        threshold=0.35,
        sample_rate=1.0,
        llm_client=judge,
        sampler=lambda: highest_possible_sample,
    )

    verdict = await grader.grade(_non_mandatory_claim(), value_est=0.1)

    # Reached the judge path (not the "skipped" short-circuit): the fake
    # judge was actually called, and the verdict reflects its label
    # rather than the skip sentinel.
    assert judge.calls == 1
    assert verdict.diagnostics != {"agentic": "skipped", "agentic_label": None}
    assert verdict.ok is True
    assert verdict.label == "SUPPORTS"

    # The precise property that disables the gate: with sample_rate=1.0,
    # even the highest value any real sampler could return is still not
    # >= sample_rate, so `not mandatory and sampler() >= sample_rate` is
    # always False and the skip branch in grade() is unreachable.
    assert (highest_possible_sample >= grader.sample_rate) is False
