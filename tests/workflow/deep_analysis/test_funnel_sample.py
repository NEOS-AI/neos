from neos.workflow.deep_analysis.funnel_sample import (
    QUESTION_CASES,
    QUESTION_SET_VERSION,
    aggregate_funnels,
    select_representative,
    stage_metrics,
)


def _funnel(
    *,
    proposed: int,
    graded: int,
    deterministic_rejected: int,
    near_miss: int,
    evidence_missing_rate: float = 0.0,
    avg_evidence_count: float = 0.0,
) -> dict:
    return {
        "proposed": proposed,
        "graded": graded,
        "deterministic_passed": graded - deterministic_rejected,
        "deterministic_rejected": deterministic_rejected,
        "agentic_attempted": 0,
        "agentic_passed": 0,
        "agentic_rejected": 0,
        "agentic_skipped": graded,
        "agentic_exhausted": 0,
        "verified": graded - deterministic_rejected,
        "rejected": deterministic_rejected,
        "unverified": 0,
        "evidence_missing_rate": evidence_missing_rate,
        "source_dead_rate": 0.0,
        "quote_score_buckets": {
            "exact": 0,
            "above_threshold": graded - near_miss,
            "near_miss": near_miss,
            "low": 0,
            "unavailable": 0,
        },
        "avg_evidence_count": avg_evidence_count,
        "avg_source_count": 1.0 if graded else 0.0,
        "avg_excerpt_chars": 20.0 if graded else 0.0,
    }


FUNNEL_A = _funnel(
    proposed=5,
    graded=4,
    deterministic_rejected=1,
    near_miss=1,
    evidence_missing_rate=0.25,
    avg_evidence_count=2.0,
)
FUNNEL_B = _funnel(
    proposed=8,
    graded=6,
    deterministic_rejected=3,
    near_miss=3,
    evidence_missing_rate=1 / 3,
    avg_evidence_count=3.0,
)

OBSERVATIONS = [
    {"case_id": "small-loss", "status": "completed", "order": 0, "signals": {"claim_funnel": _funnel(proposed=4, graded=2, deterministic_rejected=1, near_miss=0)}},
    {"case_id": "middle-loss", "status": "completed", "order": 1, "signals": {"claim_funnel": _funnel(proposed=6, graded=5, deterministic_rejected=2, near_miss=0)}},
    {"case_id": "large-loss", "status": "completed", "order": 2, "signals": {"claim_funnel": _funnel(proposed=12, graded=9, deterministic_rejected=3, near_miss=0)}},
    {"case_id": "ignored", "status": "failed", "order": 3, "signals": {"claim_funnel": _funnel(proposed=100, graded=100, deterministic_rejected=100, near_miss=0)}},
]

TIED_OBSERVATIONS = [
    {"case_id": "first", "status": "completed", "order": 0, "signals": {"claim_funnel": _funnel(proposed=3, graded=2, deterministic_rejected=1, near_miss=0)}},
    {"case_id": "second", "status": "completed", "order": 1, "signals": {"claim_funnel": _funnel(proposed=3, graded=2, deterministic_rejected=1, near_miss=0)}},
]


def test_question_set_is_versioned_and_mixed():
    assert QUESTION_SET_VERSION == "mixed-v1"
    assert [case.category for case in QUESTION_CASES] == [
        "fact", "fact", "technical", "technical", "causal_policy"
    ]
    assert len({case.question for case in QUESTION_CASES}) == 5


def test_stage_metrics_expose_counts_denominators_and_rates():
    funnel = {
        "proposed": 10, "graded": 8,
        "deterministic_rejected": 3,
        "agentic_rejected": 1, "agentic_exhausted": 1,
        "rejected": 2, "unverified": 1,
    }
    assert stage_metrics(funnel) == {
        "proposal_to_grade": {"count": 2, "denominator": 10, "rate": 0.2},
        "deterministic_rejection": {"count": 3, "denominator": 8, "rate": 0.375},
        "agentic_loss": {"count": 2, "denominator": 8, "rate": 0.25},
        "final_unresolved": {"count": 3, "denominator": 8, "rate": 0.375},
    }


def test_aggregate_funnels_recomputes_weighted_rates_and_averages():
    combined = aggregate_funnels([FUNNEL_A, FUNNEL_B])
    assert combined["graded"] == 10
    assert combined["evidence_missing_rate"] == 0.3
    assert combined["avg_evidence_count"] == 2.6
    assert combined["quote_score_buckets"]["near_miss"] == 4


def test_representative_contains_dominant_loss_and_is_closest_to_median():
    selected = select_representative(OBSERVATIONS)
    assert selected["dominant_stage"] == "deterministic_rejection"
    assert selected["case_id"] == "middle-loss"


def test_representative_ties_follow_fixed_question_order():
    assert select_representative(TIED_OBSERVATIONS)["case_id"] == "first"


def test_representative_returns_none_without_completed_run():
    assert select_representative([{**OBSERVATIONS[0], "status": "failed"}]) is None


def test_zero_graded_representative_is_first_completed_observation():
    observations = [
        {"case_id": "second", "status": "completed", "order": 1, "signals": {"claim_funnel": _funnel(proposed=20, graded=0, deterministic_rejected=0, near_miss=0)}},
        {"case_id": "first", "status": "completed", "order": 0, "signals": {"claim_funnel": _funnel(proposed=0, graded=0, deterministic_rejected=0, near_miss=0)}},
    ]
    assert select_representative(observations)["case_id"] == "first"
