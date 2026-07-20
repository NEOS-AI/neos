"""Bounded execution and run-scoped collection for funnel samples."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select, text

import neos.database.models  # noqa: F401 - register DARun's users FK target
from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DARun
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService
from neos.workflow.deep_analysis.funnel_sample import (
    QUESTION_CASES,
    QUESTION_SET_VERSION,
    QuestionCase,
    aggregate_funnels,
    select_representative,
    stage_metrics,
)
from neos.workflow.deep_analysis.jobs import execute_run
from neos.workflow.deep_analysis.ledger import Ledger, create_run


class PreflightError(RuntimeError):
    """Raised when required production dependencies are unavailable."""


class _CreatedRunError(RuntimeError):
    """Preserve a committed run identifier and fixed failure stage."""

    def __init__(self, run_id: str, stage: str, cause: Exception) -> None:
        super().__init__(f"created run failed during {stage}")
        self.run_id = run_id
        self.stage = stage
        self.cause = cause


_RUN_METADATA_FIELDS = (
    "case_id",
    "category",
    "question",
    "profile",
    "status",
    "run_id",
    "elapsed_seconds",
    "tokens_spent",
    "order",
    "error",
)
_FUNNEL_FIELDS = (
    "proposed",
    "graded",
    "deterministic_passed",
    "deterministic_rejected",
    "agentic_attempted",
    "agentic_passed",
    "agentic_rejected",
    "agentic_skipped",
    "agentic_exhausted",
    "verified",
    "rejected",
    "unverified",
    "evidence_missing_rate",
    "source_dead_rate",
    "avg_evidence_count",
    "avg_source_count",
    "avg_excerpt_chars",
    "quote_score_buckets",
    "confidence_clamped_count",
    "confidence_clamped_by_source_count",
)
_QUOTE_BUCKETS = (
    "exact",
    "above_threshold",
    "near_miss",
    "low",
    "unavailable",
)
_CONFIDENCE_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")
_ERROR_TYPE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STAGES = {
    "proposal_to_grade",
    "deterministic_rejection",
    "agentic_loss",
    "final_unresolved",
}
_QUESTIONS_SCHEMA_VERSION = "1"


def _declared_questions(cases: Sequence[QuestionCase]) -> dict[str, Any]:
    return {
        "schema_version": _QUESTIONS_SCHEMA_VERSION,
        "items": [
            {
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
            }
            for case in cases
        ],
    }


def _safe_run_metadata(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    metadata = {
        key: run[key]
        for key in _RUN_METADATA_FIELDS
        if key in run and key != "error"
    }
    error = run.get("error")
    if isinstance(error, dict):
        stage = error.get("stage", "execution")
        error_type = error.get("type")
        metadata["error"] = {
            "type": (
                error_type
                if isinstance(error_type, str)
                and _ERROR_TYPE_PATTERN.fullmatch(error_type)
                else "UnknownError"
            ),
            "stage": stage
            if stage in {"execution", "collection"}
            else "execution",
        }
    return metadata


def _safe_funnel(funnel: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key in _FUNNEL_FIELDS:
        value = funnel.get(key)
        if key == "quote_score_buckets":
            if isinstance(value, dict):
                safe[key] = {
                    bucket: count
                    for bucket in _QUOTE_BUCKETS
                    if (count := value.get(bucket)) is not None
                    and _is_safe_number(count)
                }
        elif key == "confidence_clamped_by_source_count":
            if isinstance(value, dict):
                safe[key] = {
                    bucket: count
                    for bucket in _CONFIDENCE_CLAMP_BUCKETS
                    if (count := value.get(bucket)) is not None
                    and _is_safe_count(count)
                }
        elif _is_safe_number(value):
            safe[key] = value
    return safe


def _is_safe_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _is_safe_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_selection(selection: Any) -> dict[str, Any] | None:
    if not isinstance(selection, dict):
        return None
    safe = {
        key: selection[key]
        for key in ("case_id", "dev_order")
        if key in selection
    }
    stage = selection.get("dominant_stage")
    safe["dominant_stage"] = stage if stage in _STAGES else "none"
    return safe


def _run_funnel(run: dict[str, Any]) -> dict[str, Any]:
    signals = run.get("signals")
    if not isinstance(signals, dict):
        return {}
    funnel = signals.get("claim_funnel")
    return _safe_funnel(funnel) if isinstance(funnel, dict) else {}


def render_report(result: dict[str, Any]) -> str:
    """Render a concise report from the artifact-safe evaluation fields."""
    raw_runs = [*result.get("dev_runs", [])]
    if result.get("default_run") is not None:
        raw_runs.append(result["default_run"])
    runs = [
        {**(_safe_run_metadata(run) or {}), "claim_funnel": _run_funnel(run)}
        for run in raw_runs
    ]
    rows = []
    for run in runs:
        funnel = run["claim_funnel"]
        rows.append(
            "| {case_id} | {profile} | {status} | {elapsed} | {tokens} | "
            "{proposed} | {graded} | {verified} | {rejected} | {unverified} |".format(
                case_id=run.get("case_id", "-"),
                profile=run.get("profile", "-"),
                status=run.get("status", "-"),
                elapsed=run.get("elapsed_seconds", "-"),
                tokens=run.get("tokens_spent", "-"),
                proposed=funnel.get("proposed", 0),
                graded=funnel.get("graded", 0),
                verified=funnel.get("verified", 0),
                rejected=funnel.get("rejected", 0),
                unverified=funnel.get("unverified", 0),
            )
        )

    aggregate = _safe_funnel(result.get("dev_funnel", {}))
    selection = _safe_selection(result.get("selection")) or {}
    stage = selection.get("dominant_stage", "none")
    metrics = stage_metrics(aggregate)
    stage_metric = metrics.get(stage, {"count": 0, "rate": 0.0})
    buckets = aggregate.get("quote_score_buckets", {})
    failures = [
        f"{run.get('case_id', '-')}/{run.get('profile', '-')}: "
        f"{run['error'].get('type', 'Exception')} at {run['error'].get('stage', 'execution')}"
        for run in runs
        if isinstance(run.get("error"), dict)
    ]
    failure_lines = "\n".join(f"- {failure}" for failure in failures) or "- None"
    default_funnel = runs[-1]["claim_funnel"] if result.get("default_run") else {}
    selected_dev = next(
        (
            run
            for run in runs[: len(result.get("dev_runs", []))]
            if run.get("case_id") == selection.get("case_id")
        ),
        {},
    )
    dev_funnel = selected_dev.get("claim_funnel", {})
    delta_fields = ("proposed", "graded", "verified", "rejected", "unverified")
    deltas = ", ".join(
        f"{field}={default_funnel.get(field, 0) - dev_funnel.get(field, 0)}"
        for field in delta_fields
    )
    return (
        "# Deep-analysis claim funnel sample\n\n"
        "| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows)
        + "\n\n"
        f"- Dominant loss stage: `{stage}` — {stage_metric['count']} "
        f"({stage_metric['rate']:.1%})\n"
        f"- Quote buckets: {json.dumps(buckets, sort_keys=True)}\n"
        f"- Evidence missing rate: {aggregate.get('evidence_missing_rate', 0):.1%}\n"
        f"- Source dead rate: {aggregate.get('source_dead_rate', 0):.1%}\n"
        f"- Default minus dev deltas: {deltas}\n\n"
        "## Failures\n\n"
        f"{failure_lines}\n\n"
        "The stages overlap, and no policy was changed.\n"
    )


def write_artifacts(
    result: dict[str, Any],
    output_root: Path,
    now: datetime | None = None,
) -> Path:
    """Write a new timestamped artifact directory without overwriting."""
    timestamp = now or datetime.now(timezone.utc)
    artifact_dir = output_root / timestamp.astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    artifact_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": result.get("schema_version"),
        "question_set_version": result.get("question_set_version"),
        "questions": _declared_questions(QUESTION_CASES),
        "dev_runs": [
            _safe_run_metadata(run) for run in result.get("dev_runs", [])
        ],
        "default_run": _safe_run_metadata(result.get("default_run")),
    }
    funnel = {
        "dev_runs": [
            {
                "case_id": run.get("case_id"),
                "profile": run.get("profile"),
                "claim_funnel": _run_funnel(run),
            }
            for run in result.get("dev_runs", [])
        ],
        "selection": _safe_selection(result.get("selection")),
        "default_run": {
            "case_id": (result.get("default_run") or {}).get("case_id"),
            "profile": (result.get("default_run") or {}).get("profile"),
            "claim_funnel": _run_funnel(result.get("default_run") or {}),
        },
        "dev_funnel": _safe_funnel(result.get("dev_funnel", {})),
    }
    json_options = {
        "ensure_ascii": False,
        "indent": 2,
        "sort_keys": True,
        "default": str,
    }
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, **json_options) + "\n"
    )
    (artifact_dir / "funnel.json").write_text(
        json.dumps(funnel, **json_options) + "\n"
    )
    (artifact_dir / "report.md").write_text(render_report(result))
    return artifact_dir


async def preflight(settings_obj, session_factory) -> None:
    missing = [
        name
        for name in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY")
        if not getattr(settings_obj, name, None)
    ]
    if missing:
        raise PreflightError(
            "missing required credentials: " + ", ".join(missing)
        )
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))


def sanitize_error(
    exc: Exception, secrets: Iterable[str | None]
) -> dict[str, str]:
    del secrets
    source = exc.cause if isinstance(exc, _CreatedRunError) else exc
    stage = getattr(exc, "stage", "execution")
    if stage not in {"execution", "collection"}:
        stage = "execution"
    return {"type": type(source).__name__, "stage": stage}


async def execute_case(
    case: QuestionCase,
    profile: str,
    *,
    session_factory=get_session_ctx,
    execute_fn=execute_run,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Execute one committed run and collect only run-scoped observations."""
    run_id: str | None = None
    stage = "execution"
    try:
        async with session_factory() as session:
            run_id = await create_run(
                session, case.question, profile
            )
            await session.commit()

        started = time.monotonic()
        await execute_fn(
            session_factory,
            run_id,
            case.question,
            profile,
            timeout_seconds=(
                settings.config.deep_analysis.job_time_limit
                if timeout_seconds is None
                else timeout_seconds
            ),
        )
        elapsed = time.monotonic() - started

        stage = "collection"
        async with session_factory() as session:
            status = await session.scalar(
                select(DARun.status).where(DARun.id == run_id)
            )
            signals = await DeepAnalysisAnalyticsService(session).signals(
                run_id=run_id
            )
            tokens_spent = await Ledger(session, run_id).total_spent()

        return {
            "case_id": case.case_id,
            "category": case.category,
            "question": case.question,
            "profile": profile,
            "status": status,
            "run_id": run_id,
            "elapsed_seconds": elapsed,
            "tokens_spent": tokens_spent,
            "signals": signals,
        }
    except Exception as exc:
        if run_id is None:
            raise
        raise _CreatedRunError(run_id, stage, exc) from exc


async def run_sample(
    *,
    cases: Sequence[QuestionCase] = QUESTION_CASES,
    execute_case_fn: Callable[
        [QuestionCase, str], Awaitable[dict[str, Any]]
    ] | None = None,
    session_factory=get_session_ctx,
    execute_fn=execute_run,
    timeout_seconds: float | None = None,
    secrets: Iterable[str | None] | None = None,
) -> dict[str, Any]:
    """Run dev cases sequentially and rerun one representative at default."""
    if execute_case_fn is None:

        async def execute_case_fn(
            case: QuestionCase, profile: str
        ) -> dict[str, Any]:
            return await execute_case(
                case,
                profile,
                session_factory=session_factory,
                execute_fn=execute_fn,
                timeout_seconds=timeout_seconds,
            )

    configured_secrets = (
        [settings.ANTHROPIC_API_KEY, settings.TAVILY_API_KEY]
        if secrets is None
        else list(secrets)
    )
    dev_runs: list[dict[str, Any]] = []
    for order, case in enumerate(cases):
        try:
            observation = await execute_case_fn(case, "dev")
            dev_runs.append({**observation, "order": order})
        except Exception as exc:
            failed = {
                "case_id": case.case_id,
                "category": case.category,
                "profile": "dev",
                "status": "failed",
                "order": order,
            }
            run_id = getattr(exc, "run_id", None)
            if run_id:
                failed["run_id"] = run_id
            failed["error"] = sanitize_error(exc, configured_secrets)
            dev_runs.append(failed)

    selected = select_representative(dev_runs)
    default_run = None
    selection = None
    if selected is not None:
        selected_case = next(
            case for case in cases if case.case_id == selected["case_id"]
        )
        selection = {
            "case_id": selected["case_id"],
            "dominant_stage": selected["dominant_stage"],
            "dev_order": selected["order"],
        }
        try:
            default_run = await execute_case_fn(selected_case, "default")
        except Exception as exc:
            default_run = {
                "case_id": selected_case.case_id,
                "category": selected_case.category,
                "profile": "default",
                "status": "failed",
                **(
                    {"run_id": exc.run_id}
                    if getattr(exc, "run_id", None)
                    else {}
                ),
                "error": sanitize_error(exc, configured_secrets),
            }

    completed_funnels = [
        item["signals"]["claim_funnel"]
        for item in dev_runs
        if item["status"] == "completed"
    ]
    return {
        "schema_version": "1",
        "question_set_version": QUESTION_SET_VERSION,
        "questions": _declared_questions(cases),
        "dev_runs": dev_runs,
        "selection": selection,
        "default_run": default_run,
        "dev_funnel": aggregate_funnels(completed_funnels),
    }
