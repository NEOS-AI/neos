import pytest

from neos.workflow.deep_analysis.claim_entailment import (
    apply_entailment_results,
)
from neos.workflow.deep_analysis.models import (
    ProposedClaim,
    ProposedEvidence,
)


pytestmark = pytest.mark.no_db


def _claims():
    evidence = [
        ProposedEvidence(
            source_url="https://example.com/source",
            excerpt="Directly supported text.",
            raw_ref="0123456789abcdef",
        )
    ]
    return [
        ProposedClaim("keep me", 0.6, evidence),
        ProposedClaim("too broad qualifier", 0.6, evidence),
        ProposedClaim("discard me", 0.6, evidence),
    ]


def test_apply_entailment_results_keeps_narrows_and_discards_atomically():
    claims = _claims()

    result = apply_entailment_results(
        claims,
        {
            "results": [
                {"index": 0, "verdict": "keep"},
                {
                    "index": 1,
                    "verdict": "narrow",
                    "narrowed_claim": "supported qualifier",
                },
                {"index": 2, "verdict": "discard"},
            ]
        },
    )

    assert result is not None
    assert [claim.text for claim in result] == [
        "keep me",
        "supported qualifier",
    ]
    assert result[0] is claims[0]
    assert result[1].confidence == claims[1].confidence
    assert result[1].evidence is claims[1].evidence


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": "not-a-list"},
        {"results": [{"index": 0, "verdict": "keep"}]},
        {
            "results": [
                {"index": 0, "verdict": "keep"},
                {"index": 0, "verdict": "keep"},
                {"index": 2, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "verdict": "keep"},
                {"index": 1, "verdict": "keep"},
                {"index": 9, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "verdict": "rewrite"},
                {"index": 1, "verdict": "keep"},
                {"index": 2, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "verdict": ["keep"]},
                {"index": 1, "verdict": "keep"},
                {"index": 2, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "verdict": "keep"},
                {
                    "index": 1,
                    "verdict": "narrow",
                    "narrowed_claim": "  ",
                },
                {"index": 2, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "verdict": "keep"},
                {
                    "index": 1,
                    "verdict": "narrow",
                    "narrowed_claim": 123,
                },
                {"index": 2, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "action": "keep"},
                {
                    "index": 1,
                    "action": "narrow",
                    "new_text": "supported qualifier",
                },
                {"index": 2, "action": "discard"},
            ]
        },
        {
            "results": [
                {
                    "index": 0,
                    "verdict": "keep",
                    "narrowed_claim": "unexpected",
                },
                {
                    "index": 1,
                    "verdict": "narrow",
                    "narrowed_claim": "supported qualifier",
                },
                {"index": 2, "verdict": "discard"},
            ]
        },
        {
            "results": [
                {"index": 0, "verdict": "keep"},
                {
                    "index": 1,
                    "verdict": "narrow",
                    "narrowed_claim": "supported qualifier",
                },
                {
                    "index": 2,
                    "verdict": "discard",
                    "narrowed_claim": "unexpected",
                },
            ]
        },
    ],
)
def test_apply_entailment_results_rejects_invalid_batch(payload):
    claims = _claims()

    assert apply_entailment_results(claims, payload) is None
    assert [claim.text for claim in claims] == [
        "keep me",
        "too broad qualifier",
        "discard me",
    ]


@pytest.mark.parametrize("payload", [[], "not-an-object", None])
def test_apply_entailment_results_rejects_non_object_payload(payload):
    assert apply_entailment_results(_claims(), payload) is None
