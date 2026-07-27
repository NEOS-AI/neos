import pytest

from neos.workflow.deep_analysis.discard_recall import (
    claim_from_event,
    false_discard_rate,
    stopping_verdict,
    value_est_from_event,
    wilson_interval,
)


pytestmark = pytest.mark.no_db


def _payload():
    return {
        "text": "discarded claim",
        "confidence": 0.6,
        "value_est": 1.0,
        "evidence": [
            {
                "source_url": "https://example.com/source",
                "excerpt": "Direct evidence.",
                "raw_ref": "0123456789abcdef",
            }
        ],
    }


def test_claim_from_event_rebuilds_claim_with_evidence():
    claim = claim_from_event(_payload())

    assert claim is not None
    assert claim.text == "discarded claim"
    assert claim.confidence == 0.6
    assert len(claim.evidence) == 1
    assert claim.evidence[0].raw_ref == "0123456789abcdef"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("text"),
        lambda p: p.update({"text": "   "}),
        lambda p: p.update({"confidence": "high"}),
        lambda p: p.update({"evidence": "not-a-list"}),
        lambda p: p.update({"evidence": [{"source_url": "u"}]}),
    ],
)
def test_claim_from_event_rejects_malformed_payload(mutate):
    payload = _payload()
    mutate(payload)

    assert claim_from_event(payload) is None


def test_value_est_from_event():
    assert value_est_from_event(_payload()) == 1.0
    assert value_est_from_event({"value_est": "x"}) is None


def test_wilson_interval_matches_known_values():
    low, high = wilson_interval(19, 38, 1.96)

    assert round(low * 100, 1) == 34.8
    assert round(high * 100, 1) == 65.2


def test_wilson_interval_handles_empty_denominator():
    assert wilson_interval(0, 0, 1.96) == (0.0, 0.0)


def test_false_discard_rate():
    assert false_discard_rate(3, 12) == 0.25
    assert false_discard_rate(0, 0) == 0.0


def test_stopping_verdict_applies_preregistered_rule():
    assert (
        stopping_verdict(0.0, 0.08, safe_upper=0.10, over_discard_lower=0.40)
        == "safe"
    )
    assert (
        stopping_verdict(0.45, 0.80, safe_upper=0.10, over_discard_lower=0.40)
        == "over_discarding"
    )
    assert (
        stopping_verdict(0.05, 0.60, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )


def test_claim_from_event_rejects_boolean_confidence():
    payload = _payload()
    payload["confidence"] = True

    assert claim_from_event(payload) is None


def test_value_est_from_event_rejects_boolean():
    assert value_est_from_event({"value_est": True}) is None
    assert value_est_from_event({"value_est": False}) is None


def test_stopping_verdict_boundaries_are_strict():
    # Exactly on a bound is not past it — both fall to inconclusive.
    assert (
        stopping_verdict(0.0, 0.10, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )
    assert (
        stopping_verdict(0.40, 1.0, safe_upper=0.10, over_discard_lower=0.40)
        == "inconclusive"
    )


def test_wilson_interval_stays_in_unit_range_at_extremes():
    low, high = wilson_interval(0, 10, 1.96)
    assert low == 0.0
    assert 0.0 < high < 1.0

    low, high = wilson_interval(10, 10, 1.96)
    assert 0.0 < low < 1.0
    assert high == 1.0
