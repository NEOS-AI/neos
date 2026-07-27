"""Phase-2 script behaviour: what counts as "verified", and what the
artifact has to record so the number can be audited afterwards.

No DB, no network, no LLM — the graders are stubs.
"""

from datetime import datetime, timezone
import json

import pytest

import scripts.deep_analysis_discard_recall as cli
from neos.config.settings import settings
from neos.workflow.deep_analysis.models import (
    ProposedClaim,
    ProposedEvidence,
    Verdict,
)


pytestmark = pytest.mark.no_db


class _StubDeterministic:
    def __init__(self, ok=True):
        self._ok = ok

    async def grade(self, claim):
        return Verdict(ok=self._ok, label=None)


class _StubAgentic:
    """Returns a fixed verdict, standing in for the judge LLM."""

    def __init__(self, verdict):
        self._verdict = verdict
        self.calls = 0

    async def grade(self, claim, value_est):
        self.calls += 1
        return self._verdict


def _claim():
    return ProposedClaim(
        text="a discarded claim",
        confidence=0.1,
        evidence=[ProposedEvidence("https://example.com", "excerpt", "ref")],
    )


async def test_judge_fail_open_is_not_counted_as_verified():
    """`AgenticGrader._judge_failed` fails open for a non-mandatory claim:
    an unparseable response or an unknown label yields
    `Verdict(ok=True, label=None)`. Discarded claims skew low-confidence and
    so skew non-mandatory, so reading `ok` alone would manufacture false
    discards on exactly the population being measured.
    """
    counters = {"judge_failed": 0}
    agentic = _StubAgentic(
        Verdict(ok=True, label=None, detail="judge_unparseable")
    )
    grade_fn = cli.make_grade_fn(_StubDeterministic(), agentic, counters)

    assert await grade_fn(_claim(), 0.1) is False
    assert counters["judge_failed"] == 1
    assert agentic.calls == 1


async def test_supporting_judgement_is_counted_as_verified():
    counters = {"judge_failed": 0}
    grade_fn = cli.make_grade_fn(
        _StubDeterministic(),
        _StubAgentic(Verdict(ok=True, label="SUPPORTS")),
        counters,
    )

    assert await grade_fn(_claim(), 0.1) is True
    assert counters["judge_failed"] == 0


async def test_rejecting_judgement_is_not_verified_and_is_not_judge_failure():
    counters = {"judge_failed": 0}
    grade_fn = cli.make_grade_fn(
        _StubDeterministic(),
        _StubAgentic(
            Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL")
        ),
        counters,
    )

    assert await grade_fn(_claim(), 0.1) is False
    # A judged rejection is a real signal, not a grader failure.
    assert counters["judge_failed"] == 0


async def test_deterministic_rejection_short_circuits_before_the_judge():
    counters = {"judge_failed": 0}
    agentic = _StubAgentic(Verdict(ok=True, label="SUPPORTS"))
    grade_fn = cli.make_grade_fn(
        _StubDeterministic(ok=False), agentic, counters
    )

    assert await grade_fn(_claim(), 0.1) is False
    assert agentic.calls == 0


def _result():
    return {
        "raw_events": 5,
        "distinct_claims": 3,
        "kept_elsewhere": 1,
        "total_discarded": 2,
        "verified": 1,
        "judge_failed": 1,
        "malformed": 0,
        "false_discard_rate": 0.5,
        "wilson_low": 0.1,
        "wilson_high": 0.9,
        "verdict": "inconclusive",
    }


def test_manifest_records_the_configuration_that_produced_the_number(tmp_path):
    artifact_dir = cli._write_artifact(
        tmp_path,
        ["run-a"],
        _result(),
        receipt=cli._receipt(
            datetime(2026, 7, 27, tzinfo=timezone.utc),
            datetime(2026, 7, 27, 0, 5, tzinfo=timezone.utc),
        ),
        fingerprint=cli._fingerprint(),
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    fingerprint = manifest["config_fingerprint"]

    # Without these the one number this work exists to produce cannot be
    # reproduced, and `judge != worker` cannot be checked after the fact.
    # Worker models must be recorded resolved, not as raw overrides -- the
    # overrides are null by default and would make the check vacuous.
    assert fingerprint["judge_model"]
    assert all(fingerprint["worker_models"].values())
    # The claim-producing models for the deep passes. (scout shares the
    # "everyday" role with judge, so it can legitimately coincide; the
    # fingerprint exists precisely so that is visible rather than assumed.)
    assert fingerprint["judge_model"] not in (
        fingerprint["worker_models"]["dig"],
        fingerprint["worker_models"]["synth"],
    )
    assert "agentic_threshold" in fingerprint
    assert "quote_match_threshold" in fingerprint
    assert "confidence_cap" in fingerprint
    # The one intentional divergence from run-time grading.
    assert fingerprint["agentic_sample_rate_override"] == 1.0

    receipt = manifest["execution_receipt"]
    assert receipt["pid"] > 0
    assert receipt["started_at"] == "2026-07-27T00:00:00Z"
    assert receipt["finished_at"] == "2026-07-27T00:05:00Z"


def test_manifest_carries_no_credential_values(tmp_path):
    artifact_dir = cli._write_artifact(
        tmp_path,
        ["run-a"],
        _result(),
        receipt=cli._receipt(
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        ),
        fingerprint=cli._fingerprint(),
    )

    raw = (artifact_dir / "manifest.json").read_text()
    secrets = [
        value
        for value in (
            settings.ANTHROPIC_API_KEY,
            settings.TAVILY_API_KEY,
        )
        if value
    ]
    for secret in secrets:
        assert str(secret) not in raw


def test_report_shows_the_collapse_from_events_to_graded_claims(tmp_path):
    artifact_dir = cli._write_artifact(
        tmp_path,
        ["run-a"],
        _result(),
        receipt={},
        fingerprint={},
    )

    report = (artifact_dir / "report.md").read_text()
    assert "Raw `claim_discarded` events: 5" in report
    assert "Distinct claims after hash merge: 3" in report
    assert "kept elsewhere in the run: 1" in report
    assert "Discarded claims graded: 2" in report
    assert "Judge failed to return a label: 1" in report

    recall = json.loads((artifact_dir / "recall.json").read_text())
    assert recall["raw_events"] == 5
    assert recall["judge_failed"] == 1
