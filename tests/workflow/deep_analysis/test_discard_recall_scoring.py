import pytest

from neos.workflow.deep_analysis.discard_recall import score_discards


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
