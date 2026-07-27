"""Score entailment-discarded claims to measure claim recall loss."""

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select

from neos.config.model_routing import resolve_model
from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAClaim, DAEvent
from neos.workflow.deep_analysis.discard_recall import (
    false_discard_rate,
    score_discards,
    stopping_verdict,
    wilson_interval,
)
from neos.workflow.deep_analysis.graders.agentic import AgenticGrader
from neos.workflow.deep_analysis.graders.deterministic import (
    DeterministicGrader,
)
from neos.workflow.deep_analysis.ledger import Ledger


# Exhaustive by design. AgenticGrader.grade() has a sampling gate
# (agentic.py:73-78) that returns ok=True — i.e. "verified" — for claims it
# never judged. At the configured rate that would silently count never-judged
# claims as false discards and make the measurement non-reproducible. 1.0
# disables it: random.random() is always < 1.0, so nothing is ever skipped.
# This is the one intentional divergence from run-time grading, so it is
# recorded in the manifest fingerprint.
_EXHAUSTIVE_SAMPLE_RATE = 1.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure entailment discard recall loss"
    )
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/deep-analysis-discard-recall"),
    )
    return parser.parse_args()


async def _load_events(session, run_ids: list[str]) -> list[dict]:
    stmt = select(DAEvent.payload).where(
        DAEvent.kind == "claim_discarded",
        DAEvent.run_id.in_(run_ids),
    )
    rows = (await session.execute(stmt)).all()
    payloads = []
    for (raw,) in rows:
        try:
            payloads.append(json.loads(raw))
        except (ValueError, TypeError):
            payloads.append(None)
    return payloads


async def _kept_hashes(session, run_ids: list[str]) -> set[str]:
    """Claim hashes that reached ``deep_analysis_claims`` for these runs.

    A question can return to ``open`` and be re-investigated, so entailment
    may discard a claim on one pass and keep it on another. A claim that was
    kept anywhere in the run cost the pipeline no recall, whatever its final
    grading status — so it must not be counted as a false discard.
    """
    stmt = select(DAClaim.hash).where(DAClaim.run_id.in_(run_ids))
    rows = (await session.execute(stmt)).all()
    return {value for (value,) in rows}


def _resolved_model(role: str, feature_override) -> str:
    return resolve_model(
        config=settings.config.model_routing,
        provider="anthropic",
        role=role,
        feature_override=feature_override,
    ).model


def _judge_model() -> str:
    # Same role/override pair the pipeline's own grader uses (service.py:60-66).
    return _resolved_model("everyday", settings.config.deep_analysis.models.judge)


def _graders(session, run_id: str):
    config = settings.config.deep_analysis
    ledger = Ledger(session, run_id)
    deterministic = DeterministicGrader(
        ledger,
        quote_threshold=config.quote_match_threshold,
        confidence_cap=config.confidence_cap,
    )
    agentic = AgenticGrader(
        judge_model=_judge_model(),
        threshold=config.agentic_threshold,
        sample_rate=_EXHAUSTIVE_SAMPLE_RATE,
    )
    return deterministic, agentic


def make_grade_fn(deterministic, agentic, counters: dict):
    """Build the pipeline-equivalent "would this have been verified?" predicate.

    A claim counts as verified only when the deterministic grader passes and
    the judge actually returned a supporting judgement. ``Verdict.ok`` alone
    is not enough: ``AgenticGrader._judge_failed`` (agentic.py:61-69) fails
    **open** for a non-mandatory claim — an unparseable response or an unknown
    label yields ``Verdict(ok=True, label=None)``. Discarded claims skew
    low-confidence and therefore skew non-mandatory, so trusting ``ok`` would
    fire that path disproportionately on exactly the population being measured
    and manufacture false discards. Those outcomes are counted into
    ``judge_failed`` instead and reported in the artifact.
    """

    async def grade_fn(claim, value_est) -> bool:
        verdict = await deterministic.grade(claim)
        if not verdict.ok:
            return False
        # Exhaustive by design: sample_rate=1.0 means the sampling gate
        # cannot blur the denominator, so ok+label=None is a judge failure
        # rather than a skipped claim.
        agentic_verdict = await agentic.grade(claim, value_est)
        if agentic_verdict.ok and agentic_verdict.label is None:
            counters["judge_failed"] += 1
            return False
        return agentic_verdict.ok and agentic_verdict.label == "SUPPORTS"

    return grade_fn


def _fingerprint() -> dict:
    """Non-secret configuration that produced this number.

    Model IDs, thresholds, and the one deliberate divergence from run-time
    grading. Configuration only — never credentials. Worker models are
    recorded **resolved**, not as raw overrides (which are usually null), so
    the `judge != worker` invariant is checkable from the artifact alone.
    """
    config = settings.config.deep_analysis
    return {
        "judge_model": _judge_model(),
        "agentic_threshold": config.agentic_threshold,
        "quote_match_threshold": config.quote_match_threshold,
        "confidence_cap": config.confidence_cap,
        "agentic_sample_rate_override": _EXHAUSTIVE_SAMPLE_RATE,
        "worker_models": {
            # Roles mirror the pipeline: worker.py:180-189 (scout/dig),
            # synthesizer.py:76-81 (synth).
            "scout": _resolved_model("everyday", config.models.scout),
            "dig": _resolved_model("powerful", config.models.dig),
            "synth": _resolved_model("powerful", config.models.synth),
        },
    }


def _receipt(started_at: datetime, finished_at: datetime) -> dict:
    """Process metadata proving this scoring run's wall-clock window."""
    return {
        "pid": os.getpid(),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
    }


def _write_artifact(
    output_root: Path,
    run_ids: list[str],
    result: dict,
    *,
    receipt: dict,
    fingerprint: dict,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = output_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=False)
    config = settings.config.deep_analysis.discard_recall
    manifest = {
        "run_ids": run_ids,
        "thresholds": {
            "wilson_z": config.wilson_z,
            "safe_upper_bound": config.safe_upper_bound,
            "over_discard_lower_bound": config.over_discard_lower_bound,
        },
        "config_fingerprint": fingerprint,
        "execution_receipt": receipt,
    }
    options = {"ensure_ascii": False, "indent": 2, "sort_keys": True}
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, **options) + "\n"
    )
    (artifact_dir / "recall.json").write_text(
        json.dumps(result, **options) + "\n"
    )
    (artifact_dir / "report.md").write_text(
        "# Entailment discard recall\n\n"
        f"- Raw `claim_discarded` events: {result['raw_events']}\n"
        f"- Distinct claims after hash merge: {result['distinct_claims']}\n"
        f"- Excluded, kept elsewhere in the run: "
        f"{result['kept_elsewhere']}\n"
        f"- Discarded claims graded: {result['total_discarded']}\n"
        f"- Would have been verified: {result['verified']}\n"
        f"- Judge failed to return a label: {result['judge_failed']}\n"
        f"- Malformed events skipped: {result['malformed']}\n"
        f"- False-discard rate: {result['false_discard_rate']:.1%}\n"
        f"- Wilson 95% CI: "
        f"[{result['wilson_low']:.1%}, {result['wilson_high']:.1%}]\n"
        f"- Pre-registered verdict: **{result['verdict']}**\n\n"
        "One claim can be discarded on several passes, so events are merged "
        "by claim hash and claims kept elsewhere in the run are excluded — "
        "the rate and interval use the distinct, not-kept count.\n\n"
        "The grader is not ground truth, so this rate is a lower bound on "
        "recall loss.\n"
    )
    return artifact_dir


async def _main(run_ids: list[str], output_root: Path) -> Path:
    config = settings.config.deep_analysis.discard_recall
    started_at = datetime.now(timezone.utc)
    totals = {
        "total_discarded": 0,
        "verified": 0,
        "malformed": 0,
        "raw_events": 0,
        "distinct_claims": 0,
        "kept_elsewhere": 0,
    }
    counters = {"judge_failed": 0}

    async with get_session_ctx() as session:
        for run_id in run_ids:
            events = await _load_events(session, [run_id])
            # Both collapses are run-scoped: claim hashes only merge within a
            # run, and separate runs are independent samples.
            kept = await _kept_hashes(session, [run_id])
            deterministic, agentic = _graders(session, run_id)
            grade_fn = make_grade_fn(deterministic, agentic, counters)

            partial = await score_discards(
                events,
                grade_fn=grade_fn,
                wilson_z=config.wilson_z,
                safe_upper=config.safe_upper_bound,
                over_discard_lower=config.over_discard_lower_bound,
                kept_hashes=kept,
            )
            for key in totals:
                totals[key] += partial[key]

    # Interval and verdict are computed once, on the pooled totals.
    low, high = wilson_interval(
        totals["verified"], totals["total_discarded"], config.wilson_z
    )
    verdict = (
        "inconclusive"
        if totals["total_discarded"] == 0
        else stopping_verdict(
            low,
            high,
            safe_upper=config.safe_upper_bound,
            over_discard_lower=config.over_discard_lower_bound,
        )
    )
    result = {
        **totals,
        **counters,
        "false_discard_rate": false_discard_rate(
            totals["verified"], totals["total_discarded"]
        ),
        "wilson_low": low,
        "wilson_high": high,
        "verdict": verdict,
    }
    return _write_artifact(
        output_root,
        run_ids,
        result,
        receipt=_receipt(started_at, datetime.now(timezone.utc)),
        fingerprint=_fingerprint(),
    )


if __name__ == "__main__":
    args = _parse_args()
    artifact = asyncio.run(_main(args.run_id, args.output_root))
    print(artifact)
