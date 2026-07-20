"""Bounded execution and run-scoped collection for funnel samples."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from sqlalchemy import select, text

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
    async with session_factory() as session:
        run_id = await create_run(
            session, case.question, profile
        )
        await session.commit()

    started = time.monotonic()
    stage = "execution"
    try:
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
        "dev_runs": dev_runs,
        "selection": selection,
        "default_run": default_run,
        "dev_funnel": aggregate_funnels(completed_funnels),
    }
