"""Q3: the claim diff between two runs of a standing question (design §5 SQ4-SQ6, SQ10).

The unit is the claim; the primary pairing key is the in-run claim hash, the
secondary key the cited evidence blobs. Only "newly verified" and "refuted"
make the owner hear about it -- dropped claims and rephrase candidates are
counted, not announced.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neos.standing.questions import (
    ClaimRecord,
    QuestionRefused,
    diff_claims,
    next_run,
    render_notice,
    validate_cron,
)
from neos.workflow.deep_analysis.text_norm import claim_hash

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def claim(text, status="verified", evidence=()):
    return ClaimRecord(claim_hash(text), text, status, frozenset(evidence))


def test_the_same_verified_claims_are_no_change() -> None:
    runs = [claim("Rates rose in May.", evidence={"b1"}), claim("Inflation fell.", evidence={"b2"})]

    diff = diff_claims(runs, runs)

    assert not diff.changed
    assert diff.summary()["newly_verified"] == []


def test_the_pairing_key_is_the_normalized_claim_hash_not_the_exact_text() -> None:
    """Case and punctuation differences are the same claim -- the in-run identity."""
    before = [claim("Rates rose in May.")]
    after = [claim("rates ROSE in may")]

    assert not diff_claims(before, after).changed


def test_a_newly_verified_claim_is_news() -> None:
    before = [claim("Rates rose in May.", evidence={"b1"})]
    after = before + [claim("The central bank paused in June.", evidence={"b9"})]

    diff = diff_claims(before, after)

    assert diff.changed
    assert [c.text for c in diff.newly_verified] == ["The central bank paused in June."]


def test_a_claim_that_was_pending_or_rejected_before_and_is_verified_now_is_news() -> None:
    before = [claim("A.", "pending"), claim("B.", "rejected")]
    after = [claim("A."), claim("B.")]

    assert {c.text for c in diff_claims(before, after).newly_verified} == {"A.", "B."}


def test_a_verified_claim_now_rejected_is_refuted() -> None:
    before = [claim("Rates rose in May.", evidence={"b1"})]
    after = [claim("Rates rose in May.", "rejected", evidence={"b1"})]

    diff = diff_claims(before, after)

    assert diff.changed
    assert [c.text for c in diff.refuted] == ["Rates rose in May."]
    assert diff.dropped == ()


def test_a_verified_claim_that_is_simply_gone_is_dropped_not_news() -> None:
    """Search luck makes claims come and go -- that alone is not worth a message."""
    before = [claim("Rates rose in May."), claim("Inflation fell.")]
    after = [claim("Inflation fell."), claim("Rates rose in May.", "unverified")]

    diff = diff_claims(before, after)

    assert not diff.changed
    assert [c.text for c in diff.dropped] == ["Rates rose in May."]


def test_a_rephrased_claim_on_the_same_evidence_is_counted_not_announced() -> None:
    before = [claim("Rates rose in May.", evidence={"blob_fed", "blob_x"})]
    after = [claim("In May the policy rate went up.", evidence={"blob_fed"})]

    diff = diff_claims(before, after)

    assert not diff.changed
    assert diff.newly_verified == ()
    assert diff.dropped == ()  # explained by the rephrasing
    [(now, partners)] = diff.rephrased
    assert now.text == "In May the policy rate went up."
    assert [p.text for p in partners] == ["Rates rose in May."]


def test_the_same_claim_on_new_evidence_is_still_the_same_claim() -> None:
    before = [claim("Rates rose in May.", evidence={"old"})]
    after = [claim("Rates rose in May.", evidence={"new"})]

    diff = diff_claims(before, after)

    assert not diff.changed and diff.rephrased == () and diff.dropped == ()


def test_new_wording_on_new_evidence_is_news() -> None:
    """The secondary key only pairs claims that share evidence."""
    before = [claim("Rates rose in May.", evidence={"b1"})]
    after = [claim("In May the policy rate went up.", evidence={"b2"})]

    diff = diff_claims(before, after)

    assert diff.changed
    assert [c.text for c in diff.newly_verified] == ["In May the policy rate went up."]
    assert [c.text for c in diff.dropped] == ["Rates rose in May."]


def test_a_claim_without_evidence_never_pairs_by_evidence() -> None:
    before = [claim("Rates rose in May.")]
    after = [claim("In May the policy rate went up.")]

    diff = diff_claims(before, after)

    assert diff.rephrased == ()
    assert len(diff.newly_verified) == 1


def test_a_refuted_claim_is_not_a_rephrase_partner() -> None:
    """Refuted is its own kind: a rephrasing must not hide it."""
    before = [claim("Rates rose in May.", evidence={"b1"})]
    after = [
        claim("Rates rose in May.", "rejected", evidence={"b1"}),
        claim("In May the policy rate went up.", evidence={"b1"}),
    ]

    diff = diff_claims(before, after)

    assert [c.text for c in diff.refuted] == ["Rates rose in May."]
    assert [c.text for c in diff.newly_verified] == ["In May the policy rate went up."]
    assert diff.rephrased == ()


def test_the_summary_stores_hashes_not_sentences() -> None:
    before = [claim("A.", evidence={"b"})]
    after = [claim("A.", "rejected"), claim("B.")]

    summary = diff_claims(before, after).summary()

    assert summary == {
        "baseline": False,
        "newly_verified": [claim_hash("B.")],
        "refuted": [claim_hash("A.")],
        "dropped": [],
        "rephrased": [],
    }


def test_the_notice_is_bounded_plain_text() -> None:
    before = [claim(f"Old {i}.") for i in range(3)]
    after = [claim(f"Old {i}.", "rejected") for i in range(3)] + [
        claim(f"New fact number {i}.\nwith a newline") for i in range(8)
    ]

    body = render_notice(
        "What changed in rates?", diff_claims(before, after), da_run_id="abcd1234", max_claims=5
    )

    assert body.startswith("[NEOS] 상시 질문의 답이 달라졌습니다: What changed in rates?")
    assert "새로 검증 8:" in body and "반증 3:" in body
    assert "- …외 3" in body
    assert body.count("New fact number") == 5
    assert "\nwith a newline" not in body  # one line per claim
    assert body.rstrip().endswith("DA 런: abcd1234")


def test_cron_must_be_valid_and_not_too_frequent() -> None:
    validate_cron("0 */6 * * *", min_interval_minutes=360, now=NOW)
    validate_cron("0 9 * * 1", min_interval_minutes=360, now=NOW)
    for expression, reason in (
        ("", "invalid_cron"),
        ("not a cron", "invalid_cron"),
        ("*/5 * * * *", "cron_too_frequent"),
        # Once a day mostly, but 09:00 and 10:00 are an hour apart.
        ("0 9,10 * * *", "cron_too_frequent"),
    ):
        with pytest.raises(QuestionRefused) as refused:
            validate_cron(expression, min_interval_minutes=360, now=NOW)
        assert refused.value.reason == reason


def test_next_run_is_utc() -> None:
    assert next_run("0 9 * * *", NOW) == datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
