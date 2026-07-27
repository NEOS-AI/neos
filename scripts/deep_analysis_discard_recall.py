"""Score entailment-discarded claims to measure claim recall loss."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select

from neos.config.model_routing import resolve_model
from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAEvent
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


def _graders(session, run_id: str):
    config = settings.config.deep_analysis
    judge_model = resolve_model(
        config=settings.config.model_routing,
        provider="anthropic",
        role="everyday",
        feature_override=config.models.judge,
    ).model
    ledger = Ledger(session, run_id)
    deterministic = DeterministicGrader(
        ledger,
        quote_threshold=config.quote_match_threshold,
        confidence_cap=config.confidence_cap,
    )
    agentic = AgenticGrader(
        judge_model=judge_model,
        threshold=config.agentic_threshold,
        sample_rate=config.agentic_sample_rate,
    )
    return deterministic, agentic


def _write_artifact(output_root: Path, run_ids: list[str], result: dict) -> Path:
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
        f"- Discarded claims graded: {result['total_discarded']}\n"
        f"- Would have been verified: {result['verified']}\n"
        f"- Malformed events skipped: {result['malformed']}\n"
        f"- False-discard rate: {result['false_discard_rate']:.1%}\n"
        f"- Wilson 95% CI: "
        f"[{result['wilson_low']:.1%}, {result['wilson_high']:.1%}]\n"
        f"- Pre-registered verdict: **{result['verdict']}**\n\n"
        "The grader is not ground truth, so this rate is a lower bound on "
        "recall loss.\n"
    )
    return artifact_dir


async def _main(run_ids: list[str], output_root: Path) -> Path:
    config = settings.config.deep_analysis.discard_recall
    totals = {"total_discarded": 0, "verified": 0, "malformed": 0}

    async with get_session_ctx() as session:
        for run_id in run_ids:
            events = await _load_events(session, [run_id])
            deterministic, agentic = _graders(session, run_id)

            async def grade_fn(claim, value_est) -> bool:
                verdict = await deterministic.grade(claim)
                if not verdict.ok:
                    return False
                # Exhaustive by design: bypass should_grade() so the
                # sampling gate cannot blur the denominator.
                agentic_verdict = await agentic.grade(claim, value_est)
                return bool(agentic_verdict.ok)

            partial = await score_discards(
                events,
                grade_fn=grade_fn,
                wilson_z=config.wilson_z,
                safe_upper=config.safe_upper_bound,
                over_discard_lower=config.over_discard_lower_bound,
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
        "false_discard_rate": false_discard_rate(
            totals["verified"], totals["total_discarded"]
        ),
        "wilson_low": low,
        "wilson_high": high,
        "verdict": verdict,
    }
    return _write_artifact(output_root, run_ids, result)


if __name__ == "__main__":
    args = _parse_args()
    artifact = asyncio.run(_main(args.run_id, args.output_root))
    print(artifact)
