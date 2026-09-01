"""Phase-2 script behaviour: what counts as "verified", and what the
artifact has to record so the number can be audited afterwards.

No DB, no network, no LLM — the graders are stubs.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from types import SimpleNamespace

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


class _RaisingAgentic:
    """Stands in for a judge call that blows up mid-pass, e.g. a transient
    ``LLMProviderError``."""

    async def grade(self, claim, value_est):
        raise RuntimeError("transient provider failure")


async def test_grading_error_is_never_counted_as_verified():
    """A missing key or one flaky judge call must not abort the whole
    exhaustive pass, and the errored claim must fail closed -- the same
    fail-open trap already fixed twice in this work (the sampling gate and
    `_judge_failed`)."""
    counters = {"judge_failed": 0, "grade_errors": 0}
    grade_fn = cli.make_grade_fn(_StubDeterministic(), _RaisingAgentic(), counters)

    assert await grade_fn(_claim(), 0.1) is False
    assert counters["grade_errors"] == 1
    assert counters["judge_failed"] == 0


async def test_grading_error_before_counters_initialised_still_tallies():
    counters = {"judge_failed": 0}
    grade_fn = cli.make_grade_fn(_StubDeterministic(), _RaisingAgentic(), counters)

    assert await grade_fn(_claim(), 0.1) is False
    assert counters["grade_errors"] == 1


async def test_claims_log_records_a_supported_verified_claim():
    counters = {"judge_failed": 0, "grade_errors": 0}
    claims_log = []
    grade_fn = cli.make_grade_fn(
        _StubDeterministic(),
        _StubAgentic(Verdict(ok=True, label="SUPPORTS")),
        counters,
        claims_log,
    )

    await grade_fn(_claim(), 0.1)

    assert claims_log == [
        {
            "text": "a discarded claim",
            "deterministic_ok": True,
            "agentic_label": "SUPPORTS",
            "verified": True,
        }
    ]


async def test_claims_log_records_deterministic_rejection_without_a_judge_call():
    counters = {"judge_failed": 0, "grade_errors": 0}
    claims_log = []
    grade_fn = cli.make_grade_fn(
        _StubDeterministic(ok=False),
        _StubAgentic(Verdict(ok=True, label="SUPPORTS")),
        counters,
        claims_log,
    )

    await grade_fn(_claim(), 0.1)

    assert claims_log == [
        {
            "text": "a discarded claim",
            "deterministic_ok": False,
            "agentic_label": None,
            "verified": False,
        }
    ]


async def test_claims_log_records_a_grading_error_as_unverified():
    counters = {"judge_failed": 0, "grade_errors": 0}
    claims_log = []
    grade_fn = cli.make_grade_fn(
        _StubDeterministic(), _RaisingAgentic(), counters, claims_log
    )

    await grade_fn(_claim(), 0.1)

    assert claims_log == [
        {
            "text": "a discarded claim",
            "deterministic_ok": True,
            "error": True,
            "verified": False,
        }
    ]


def test_dedupe_preserving_order_removes_duplicate_run_ids():
    assert cli._dedupe_preserving_order(
        ["run-a", "run-b", "run-a", "run-c", "run-b"]
    ) == ["run-a", "run-b", "run-c"]


class _HealthySession:
    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


@asynccontextmanager
async def _healthy_session_factory():
    yield _HealthySession()


def _answering_probe(probed: list[str] | None = None):
    async def probe(model: str) -> None:
        if probed is not None:
            probed.append(model)

    return probe


def test_preflight_passes_with_anthropic_key_and_reachable_database():
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY="sk-configured")
    asyncio.run(
        cli.preflight(
            fake_settings, _healthy_session_factory, probe=_answering_probe()
        )
    )


def test_preflight_lists_missing_anthropic_key_without_its_value():
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY=None)
    with pytest.raises(cli.PreflightError, match="ANTHROPIC_API_KEY"):
        asyncio.run(
            cli.preflight(
                fake_settings,
                _healthy_session_factory,
                probe=_answering_probe(),
            )
        )


def test_preflight_probes_the_judge_because_the_judge_is_what_it_spends():
    """PREFLIGHT2 -- presence of a key is not evidence that it works.

    This script grades **every** discarded claim with a real judge call. A
    present-but-rejected key does not stop it: `grade_fn` swallows the
    provider error per claim into `grade_errors` and returns "not verified",
    so a dead credential produces a complete artifact reporting a
    false-discard rate that is an artefact of the outage. D94 taught the
    sample runner to place a real call; this caller kept its own
    presence-only copy, so the lesson arrived in one place only.
    """
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY="sk-configured")
    probed: list[str] = []
    asyncio.run(
        cli.preflight(
            fake_settings,
            _healthy_session_factory,
            probe=_answering_probe(probed),
        )
    )
    assert probed == [cli._judge_model()]


def test_preflight_fails_when_the_judge_model_refuses_the_probe():
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY="sk-live-but-revoked")

    async def rejecting_probe(model: str) -> None:
        raise RuntimeError("401 authentication_error")

    with pytest.raises(cli.PreflightError, match="401") as excinfo:
        asyncio.run(
            cli.preflight(
                fake_settings, _healthy_session_factory, probe=rejecting_probe
            )
        )
    assert "sk-live-but-revoked" not in str(excinfo.value)


def test_preflight_does_not_spend_probes_on_models_this_script_never_calls():
    """Only the judge runs here -- the workers are fingerprint, not callers.

    Probing them would burn tokens proving a dependency this measurement does
    not have, and would make an unrelated worker outage block a scoring pass
    that would have succeeded.
    """
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY="sk-configured")
    probed: list[str] = []
    asyncio.run(
        cli.preflight(
            fake_settings,
            _healthy_session_factory,
            probe=_answering_probe(probed),
        )
    )
    assert len(probed) == 1


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


def test_write_artifact_defaults_per_run_and_claims_when_omitted(tmp_path):
    """Existing callers that don't pass per_run/claims must keep working,
    and the artifact must still declare an (empty) breakdown rather than
    omitting the keys."""
    artifact_dir = cli._write_artifact(
        tmp_path, ["run-a"], _result(), receipt={}, fingerprint={}
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    assert manifest["per_run"] == []
    claims = json.loads((artifact_dir / "claims.json").read_text())
    assert claims == {"claims": []}


def test_write_artifact_reports_a_zero_count_run_so_an_unknown_id_is_visible(
    tmp_path,
):
    per_run = [
        {
            "run_id": "known-run",
            "raw_events": 5,
            "distinct_claims": 3,
            "kept_elsewhere": 1,
            "total_discarded": 2,
            "verified": 1,
            "malformed": 0,
        },
        {
            "run_id": "unknown-or-empty-run",
            "raw_events": 0,
            "distinct_claims": 0,
            "kept_elsewhere": 0,
            "total_discarded": 0,
            "verified": 0,
            "malformed": 0,
        },
    ]

    artifact_dir = cli._write_artifact(
        tmp_path,
        ["known-run", "unknown-or-empty-run"],
        _result(),
        receipt={},
        fingerprint={},
        per_run=per_run,
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    assert manifest["per_run"] == per_run
    unknown = next(
        row
        for row in manifest["per_run"]
        if row["run_id"] == "unknown-or-empty-run"
    )
    # Zero, not absent -- an unknown run must show up rather than being
    # silently folded into the pooled total.
    assert unknown["raw_events"] == 0


def test_write_artifact_writes_a_separate_claims_file_for_human_adjudication(
    tmp_path,
):
    claims = [
        {
            "text": "a claim the grader flagged",
            "deterministic_ok": True,
            "agentic_label": "PARTIAL",
            "verified": False,
        }
    ]

    artifact_dir = cli._write_artifact(
        tmp_path,
        ["run-a"],
        _result(),
        receipt={},
        fingerprint={},
        claims=claims,
    )

    # Separate from recall.json -- spec §4 wants the aggregate small and the
    # per-claim detail elsewhere.
    recall = json.loads((artifact_dir / "recall.json").read_text())
    assert "claims" not in recall

    claims_file = json.loads((artifact_dir / "claims.json").read_text())
    assert claims_file == {"claims": claims}


def test_report_shows_grading_errors_and_points_to_claims_file(tmp_path):
    result = _result()
    result["grade_errors"] = 2

    artifact_dir = cli._write_artifact(
        tmp_path, ["run-a"], result, receipt={}, fingerprint={}
    )

    report = (artifact_dir / "report.md").read_text()
    assert "Grading errors (never counted as verified): 2" in report
    assert "claims.json" in report


@asynccontextmanager
async def _fake_session_ctx():
    yield object()


def test_main_dedupes_run_ids_and_makes_an_unknown_run_visible(
    monkeypatch, tmp_path
):
    """End-to-end through the real `_main`, with the DB/grader boundary
    faked out: duplicate --run-id must not double-count, and a run with no
    `claim_discarded` events (unknown or genuinely empty) must show up as a
    zero-count row rather than vanish into the pooled total."""

    async def fake_preflight(*_args):
        return None

    async def fake_load_events(_session, run_ids):
        (run_id,) = run_ids
        if run_id != "known-run":
            return []
        return [
            {
                "text": "a discarded claim",
                "confidence": 0.2,
                "value_est": 0.5,
                "evidence": [],
            }
        ]

    async def fake_kept_hashes(_session, _run_ids):
        return set()

    def fake_graders(_session, _run_id):
        return (
            _StubDeterministic(ok=False),
            _StubAgentic(Verdict(ok=True, label="SUPPORTS")),
        )

    monkeypatch.setattr(cli, "preflight", fake_preflight)
    monkeypatch.setattr(cli, "get_session_ctx", _fake_session_ctx)
    monkeypatch.setattr(cli, "_load_events", fake_load_events)
    monkeypatch.setattr(cli, "_kept_hashes", fake_kept_hashes)
    monkeypatch.setattr(cli, "_graders", fake_graders)

    artifact_dir = asyncio.run(
        cli._main(
            ["known-run", "known-run", "unknown-run"], tmp_path
        )
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    # Deduped, order preserved -- the repeated "known-run" collapses to one.
    assert manifest["run_ids"] == ["known-run", "unknown-run"]

    per_run = {row["run_id"]: row for row in manifest["per_run"]}
    assert set(per_run) == {"known-run", "unknown-run"}
    assert per_run["known-run"]["raw_events"] == 1
    assert per_run["unknown-run"]["raw_events"] == 0

    recall = json.loads((artifact_dir / "recall.json").read_text())
    # The one discarded claim was deterministic-rejected by the stub, so it
    # is graded once, not twice -- proof the duplicate didn't double-count.
    assert recall["total_discarded"] == 1

