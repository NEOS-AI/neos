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

from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAClaim, DAEvent
from neos.workflow.deep_analysis.discard_recall import (
    ScoringSession,
    discards_needed_for_safe,
    false_discard_rate,
    pool_sessions,
    score_discards,
    stopping_verdict,
    wilson_interval,
)
from neos.workflow.deep_analysis.funnel_sample_runner import (
    # Re-exported on purpose: `PreflightError` is this module's public failure
    # type for its callers and tests, and a second class by the same name
    # would let one be raised and the other caught.
    PreflightError as PreflightError,
    preflight as _shared_preflight,
)
from neos.workflow.deep_analysis.graders.agentic import AgenticGrader
from neos.workflow.deep_analysis.graders.deterministic import (
    DeterministicGrader,
)
from neos.workflow.deep_analysis.ledger import Ledger
from neos.workflow.deep_analysis.model_roles import resolve_harness_model


# Exhaustive by design. AgenticGrader.grade() has a sampling gate
# (agentic.py:73-78) that returns ok=True — i.e. "verified" — for claims it
# never judged. At the configured rate that would silently count never-judged
# claims as false discards and make the measurement non-reproducible. 1.0
# disables it: random.random() is always < 1.0, so nothing is ever skipped.
# This is the one intentional divergence from run-time grading, so it is
# recorded in the manifest fingerprint.
_EXHAUSTIVE_SAMPLE_RATE = 1.0

#: 이 스크립트가 요구하는 시크릿. 표본 러너와 달리 검색을 하지 않으므로
#: `TAVILY_API_KEY` 는 빠진다 -- 쓰지 않는 것을 요구하면 사람이 검사를 끄는
#: 법을 배우고, 그러면 아래 프로브까지 함께 꺼진다.
_REQUIRED_CREDENTIALS = ("ANTHROPIC_API_KEY",)


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
    parser.add_argument(
        "--accumulate",
        action="store_true",
        help=(
            "Pool this scoring with every prior artifact under --output-root "
            "(C1). The pre-registered rule cannot return 'safe' below n=35 "
            "distinct discards and one 5+1 run yields roughly 16, so a "
            "verdict requires pooling across sittings. Refuses to pool "
            "sessions whose config fingerprints differ or whose run sets "
            "overlap."
        ),
    )
    return parser.parse_args()


def _dedupe_preserving_order(run_ids: list[str]) -> list[str]:
    """Repeated ``--run-id`` values must not double-count a run's claims."""
    return list(dict.fromkeys(run_ids))


async def preflight(settings_obj, session_factory, **kwargs) -> None:
    """Fail before any judge token is spent, not partway through.

    Delegates to ``funnel_sample_runner.preflight`` rather than mirroring its
    shape (PREFLIGHT2). The earlier version *said* it mirrored that function
    and, as of D94, no longer did: the sample runner had been taught to place
    a real call, while this one still checked that ``ANTHROPIC_API_KEY`` was
    a non-empty string. That gap matters more here than the docstring drift
    suggests -- this script spends judge tokens on **every discarded claim**
    in the requested runs, so a present-but-rejected key means the whole
    exhaustive pass fails claim by claim into ``counters["grade_errors"]``,
    each one counted **not verified**, and the artifact reports a
    false-discard rate produced by a dead credential.

    Only the judge is probed because only the judge is called: the
    deterministic grader does no LLM work, and the worker models appear in
    the fingerprint for the ``judge != worker`` check, not on any call path
    here. Probing them would spend tokens to prove something this run does
    not depend on.
    """
    await _shared_preflight(
        settings_obj,
        session_factory,
        models=(resolve_harness_model("judge").model,),
        credentials=_REQUIRED_CREDENTIALS,
        **kwargs,
    )


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


def _judge_model() -> str:
    """The model the pipeline's own grader resolves to.

    Via ``model_roles`` rather than a local ``resolve_model`` call: that
    module exists to be the single caller, and this script was holding the
    eleventh copy of the role literals it was created to collapse. The copy
    also passed ``provider="anthropic"`` unconditionally, which is the exact
    misreport ``_provider_for`` was written to stop -- harmless while the
    judge happens to be an Anthropic model, silent the moment it is not, and
    it lands in an artifact that cannot be regenerated.
    """
    return resolve_harness_model("judge").model


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
        max_output_tokens=config.judge_max_output_tokens,
    )
    return deterministic, agentic


def make_grade_fn(deterministic, agentic, counters: dict, claims_log=None):
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

    A transient grading error (e.g. an ``LLMProviderError`` mid-pass) is
    caught here rather than left to abort the whole exhaustive run — judge
    tokens already spent on every other claim would otherwise be wasted with
    no artifact to show for them. The errored claim is counted into
    ``counters["grade_errors"]`` and **never** counted as verified: that is
    the same fail-open trap already fixed twice in this work (the
    ``should_grade`` sampling gate and ``_judge_failed``), so an exception
    must fail closed here too.

    If ``claims_log`` is given, one record per graded claim is appended to it
    (claim text, deterministic outcome, agentic label, whether it counted as
    verified) so a human can adjudicate the ones the grader disagreed with.
    """

    async def grade_fn(claim, value_est) -> bool:
        entry = {"text": claim.text} if claims_log is not None else None
        try:
            verdict = await deterministic.grade(claim)
            if not verdict.ok:
                if entry is not None:
                    entry["deterministic_ok"] = False
                    entry["agentic_label"] = None
                    entry["verified"] = False
                    claims_log.append(entry)
                return False
            if entry is not None:
                entry["deterministic_ok"] = True

            # Exhaustive by design: sample_rate=1.0 means the sampling gate
            # cannot blur the denominator, so ok+label=None is a judge
            # failure rather than a skipped claim.
            agentic_verdict = await agentic.grade(claim, value_est)
            if entry is not None:
                entry["agentic_label"] = agentic_verdict.label

            if agentic_verdict.ok and agentic_verdict.label is None:
                counters["judge_failed"] += 1
                if entry is not None:
                    entry["verified"] = False
                    claims_log.append(entry)
                return False

            verified = (
                agentic_verdict.ok and agentic_verdict.label == "SUPPORTS"
            )
            if entry is not None:
                entry["verified"] = verified
                claims_log.append(entry)
            return verified
        except Exception:  # noqa: BLE001 - one bad claim must not sink the run
            counters["grade_errors"] = counters.get("grade_errors", 0) + 1
            if entry is not None:
                entry["error"] = True
                entry["verified"] = False
                claims_log.append(entry)
            return False

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
            # Roles come from `HARNESS_ROLES`, not from literals repeated
            # here -- the pipeline and this fingerprint must not be able to
            # disagree about which role a worker plays.
            name: resolve_harness_model(name).model
            for name in ("scout", "dig", "synth")
        },
    }


def load_prior_sessions(output_root: Path) -> list[ScoringSession]:
    """`output_root` 아래의 이전 채점 아티팩트를 읽는다 (C1 누적).

    읽지 못하는 디렉터리는 **건너뛰지 않고 무시한다** -- 정확히는, 두 파일이
    다 없거나 형태가 틀린 디렉터리는 채점 세션이 아니므로 세션 목록에
    들어가지 않는다. 반쯤 쓰인 아티팩트를 세션으로 받아들이면 분모에 근거
    없는 수가 들어가고, 그것이 이 측정에서 가장 비싼 실수다.
    """
    sessions: list[ScoringSession] = []
    if not output_root.is_dir():
        return sessions
    for entry in sorted(output_root.iterdir()):
        manifest_path = entry / "manifest.json"
        recall_path = entry / "recall.json"
        if not (manifest_path.is_file() and recall_path.is_file()):
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
            recall = json.loads(recall_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or not isinstance(recall, dict):
            continue
        if "config_fingerprint" not in manifest:
            continue
        try:
            total = int(recall["total_discarded"])
            verified = int(recall["verified"])
        except (KeyError, TypeError, ValueError):
            continue
        sessions.append(
            ScoringSession(
                artifact=entry.name,
                fingerprint=manifest["config_fingerprint"],
                run_ids=tuple(manifest.get("run_ids") or ()),
                total_discarded=total,
                verified=verified,
            )
        )
    return sessions


def _accumulated(
    output_root: Path,
    current: ScoringSession,
) -> dict:
    """이번 채점을 이전 것들과 합친 결과. 합칠 수 없으면 그 사유를 담는다."""
    config = settings.config.deep_analysis.discard_recall
    pooled = pool_sessions(
        [*load_prior_sessions(output_root), current],
        wilson_z=config.wilson_z,
        safe_upper=config.safe_upper_bound,
        over_discard_lower=config.over_discard_lower_bound,
    )
    if "total_discarded" in pooled:
        pooled["additional_discards_for_safe"] = discards_needed_for_safe(
            pooled["verified"],
            pooled["total_discarded"],
            wilson_z=config.wilson_z,
            safe_upper=config.safe_upper_bound,
        )
    return pooled


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
    per_run=None,
    claims=None,
    accumulated=None,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = output_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=False)
    config = settings.config.deep_analysis.discard_recall
    manifest = {
        "run_ids": run_ids,
        # One row per requested run, even a run with zero events -- an
        # unknown or empty --run-id must be visible here, not silently
        # absorbed into the pooled total.
        "per_run": list(per_run) if per_run is not None else [],
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
    # 별도 파일이다. `recall.json` 은 **이번 채점**의 수이고 여기는 여러
    # 세션을 합친 수라, 한 파일에 담으면 다음 사람이 어느 분모를 인용하는지
    # 알 수 없다 -- D48 이 지표 이름 하나로 표본 하나를 치른 그 실수다.
    if accumulated is not None:
        (artifact_dir / "accumulated.json").write_text(
            json.dumps(accumulated, **options) + "\n"
        )
    # Separate file, not folded into recall.json -- spec §2.2 requires a
    # human to adjudicate the claims the grader flagged, and that needs the
    # claim text and per-stage outcome the aggregate alone can't provide.
    (artifact_dir / "claims.json").write_text(
        json.dumps(
            {"claims": list(claims) if claims is not None else []},
            **options,
        )
        + "\n"
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
        f"- Grading errors (never counted as verified): "
        f"{result.get('grade_errors', 0)}\n"
        f"- Malformed events skipped: {result['malformed']}\n"
        f"- False-discard rate: {result['false_discard_rate']:.1%}\n"
        f"- Wilson 95% CI: "
        f"[{result['wilson_low']:.1%}, {result['wilson_high']:.1%}]\n"
        f"- Pre-registered verdict: **{result['verdict']}**\n\n"
        "One claim can be discarded on several passes, so events are merged "
        "by claim hash and claims kept elsewhere in the run are excluded — "
        "the rate and interval use the distinct, not-kept count.\n\n"
        "The grader is not ground truth, so this rate is a lower bound on "
        "recall loss. See `claims.json` for the per-claim breakdown to "
        "adjudicate.\n"
    )
    return artifact_dir


async def _main(
    run_ids: list[str], output_root: Path, *, accumulate: bool = False
) -> Path:
    run_ids = _dedupe_preserving_order(run_ids)
    await preflight(settings, get_session_ctx)
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
    counters = {"judge_failed": 0, "grade_errors": 0}
    claims_log: list[dict] = []
    per_run: list[dict] = []

    async with get_session_ctx() as session:
        for run_id in run_ids:
            events = await _load_events(session, [run_id])
            # Both collapses are run-scoped: claim hashes only merge within a
            # run, and separate runs are independent samples.
            kept = await _kept_hashes(session, [run_id])
            deterministic, agentic = _graders(session, run_id)
            grade_fn = make_grade_fn(
                deterministic, agentic, counters, claims_log
            )

            partial = await score_discards(
                events,
                grade_fn=grade_fn,
                wilson_z=config.wilson_z,
                safe_upper=config.safe_upper_bound,
                over_discard_lower=config.over_discard_lower_bound,
                kept_hashes=kept,
            )
            per_run.append(
                {"run_id": run_id, **{key: partial[key] for key in totals}}
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
    fingerprint = _fingerprint()
    # 이전 아티팩트는 **쓰기 전에** 읽는다. 쓴 뒤에 읽으면 이번 세션이
    # 디스크에서 한 번, 인자로 한 번 -- 두 번 세어져 분모가 부풀고 Wilson
    # 구간이 실제보다 좁아진다. `pool_sessions` 의 run 중복 검사가 그것을
    # 잡겠지만, 잡히지 않게 부르는 것이 낫다.
    accumulated = (
        _accumulated(
            output_root,
            ScoringSession(
                artifact="(this run)",
                fingerprint=fingerprint,
                run_ids=tuple(run_ids),
                total_discarded=totals["total_discarded"],
                verified=totals["verified"],
            ),
        )
        if accumulate
        else None
    )
    return _write_artifact(
        output_root,
        run_ids,
        result,
        receipt=_receipt(started_at, datetime.now(timezone.utc)),
        fingerprint=fingerprint,
        per_run=per_run,
        claims=claims_log,
        accumulated=accumulated,
    )


if __name__ == "__main__":
    args = _parse_args()
    artifact = asyncio.run(
        _main(args.run_id, args.output_root, accumulate=args.accumulate)
    )
    print(artifact)
