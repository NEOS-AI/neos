"""Enqueue a GEPA opt job.

This module must not write the learned_lessons table. It does not add an HTTP route.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from neos.config.settings import settings
from neos.gepa_opt.evaluators import get_evaluator


def submit_gepa_opt_job(run_id: str, owner_namespace: str) -> str:
    """Queue the job when Celery and learn.gepa_opt are both on.

    Either flag off returns ``refused`` and does not enqueue. The task body
    is never called inline.
    """
    if not settings.config.celery.enabled or not settings.config.learn.gepa_opt:
        return "refused"
    result = run_gepa_opt_job.apply_async(
        args=[run_id, owner_namespace],
        queue="gepa_opt",
    )
    return getattr(result, "id", None) or "queued"


@shared_task(
    name="neos.tasks.run_gepa_opt_job",
    bind=True,
    max_retries=2,
    soft_time_limit=1800,
    time_limit=2100,
)
def run_gepa_opt_job(self, run_id: str, owner_namespace: str) -> str:
    """Claim the run. An empty evaluator registry fails it and inserts no overlay."""
    from neos.gepa_opt.store import GepaOptStore
    from neos.learn.lessons import resolve_lesson_session_factory

    if not settings.config.celery.enabled or not settings.config.learn.gepa_opt:
        return "refused"
    store = GepaOptStore(resolve_lesson_session_factory())
    task_id = getattr(getattr(self, "request", None), "id", None) or "inline"
    try:
        return asyncio.run(
            execute_gepa_opt_job(
                store,
                run_id=run_id,
                owner_namespace=owner_namespace,
                celery_task_id=str(task_id),
            )
        )
    except SoftTimeLimitExceeded as exc:
        if _retry_after_soft_limit(self, exc) == "exhausted":
            asyncio.run(store.fail_run(run_id, owner_namespace, "soft_time_limit"))
            return "soft_time_limit"


async def execute_gepa_opt_job(
    store,
    *,
    run_id: str,
    owner_namespace: str,
    celery_task_id: str,
    surface: str = "coding_overlay",
    reflector: Any = None,
) -> str:
    """Lost claims return without writing. No evaluator fails the run.

    A registered evaluator runs the in-process search. Success stages one overlay.
    """
    claim_state = await store.claim(run_id, owner_namespace, celery_task_id)
    if claim_state == "lost":
        return "lost"
    evaluator = get_evaluator(surface)
    if evaluator is None:
        await store.fail_run(run_id, owner_namespace, "no_evaluator")
        return "no_evaluator"
    bundle = await store.load_bundle(run_id, owner_namespace)
    from neos.gepa_opt.engine import run_search
    from neos.gepa_opt.types import EngineConfig

    search_kwargs: dict[str, Any] = {
        "journal": _StoreJournal(store, run_id, owner_namespace),
        "seed_candidate_id": str(bundle["seed_candidate_id"]),
    }
    if claim_state == "resume":
        search_kwargs.update(
            {
                "prior_candidates": bundle.get("candidates") or [],
                "start_iteration": int(bundle.get("iteration") or 0),
                "evals_used": int(bundle.get("evals_used") or 0),
                "tokens_used": int(bundle.get("reflector_tokens_used") or 0),
            }
        )
    result = await run_search(
        config=EngineConfig(
            bundle["engine_label"],
            bool(bundle["pareto_enabled"]),
            component_cursor=int(bundle["component_cursor"]),
        ),
        seed=bundle["seed"],
        train=bundle["train"],
        val=bundle["val"],
        test=bundle["test"],
        max_evals=int(bundle["max_evals"]),
        max_token_cost=int(bundle["max_token_cost"]),
        evaluator=evaluator,
        reflector=reflector if reflector is not None else _model_reflector(run_id),
        **search_kwargs,
    )
    if result.overlay is None:
        await store.fail_run(run_id, owner_namespace, result.error_code or "failed")
        return "failed"
    winner = next(
        row
        for row in reversed(result.candidates)
        if row["components"] == result.overlay["components"] and row["accepted"]
    )
    candidate_id = str(winner.get("candidate_id") or bundle["seed_candidate_id"])
    await store.stage_overlay(
        overlay_id=str(uuid.uuid4()),
        owner_namespace=owner_namespace,
        surface=bundle.get("surface") or surface,
        candidate_id=candidate_id,
        run_id=run_id,
    )
    await store.mark_succeeded(run_id, owner_namespace)
    return "staged"


class _StoreJournal:
    """Writes each committed search step before the next iteration starts."""

    def __init__(self, store: Any, run_id: str, owner_namespace: str) -> None:
        self._store = store
        self._run_id = run_id
        self._owner = owner_namespace

    async def seed_scored(
        self,
        candidate: Mapping[str, Any],
        scores: Sequence[Mapping[str, Any]],
        evals_used: int,
        tokens_used: int,
    ) -> None:
        await self._store.record_seed_evaluation(
            run_id=self._run_id,
            owner_namespace=self._owner,
            candidate_id=str(candidate["candidate_id"]),
            val_mean=candidate.get("val_mean"),
            scores=scores,
            evals_used=evals_used,
            tokens_used=tokens_used,
        )

    async def candidate_committed(
        self,
        candidate: Mapping[str, Any],
        scores: Sequence[Mapping[str, Any]],
        *,
        advance_cursor: bool,
        wins_best: bool,
        evals_used: int,
        tokens_used: int,
    ) -> str:
        return await self._store.commit_iteration(
            run_id=self._run_id,
            owner_namespace=self._owner,
            candidate=candidate,
            scores=scores,
            advance_cursor=advance_cursor,
            best_candidate_id=None,
            evals_used=evals_used,
            tokens_used=tokens_used,
            wins_best=wins_best,
        )

    async def cursor_advanced(self, *, evals_used: int, tokens_used: int) -> None:
        await self._store.advance_cursor(
            run_id=self._run_id,
            owner_namespace=self._owner,
            evals_used=evals_used,
            tokens_used=tokens_used,
        )

    async def test_scored(
        self,
        candidate_id: str,
        test_mean: float | None,
        scores: Sequence[Mapping[str, Any]],
    ) -> None:
        await self._store.record_test_scores(
            owner_namespace=self._owner,
            candidate_id=candidate_id,
            test_mean=test_mean,
            scores=scores,
        )


def _retry_after_soft_limit(task: Any, exc: BaseException) -> str | None:
    """Ask Celery to resume. Exhausted retries return ``exhausted`` and insert no overlay."""
    try:
        raise task.retry(exc=exc, countdown=0)
    except SoftTimeLimitExceeded:
        return "exhausted"


def _model_reflector(run_id: str):
    """Coding-model reflector. Tests pass their own reflector instead."""

    async def reflect(component_name: str, curr_param: str, side_info_text: str) -> Any:
        from neos.gepa_opt.provider import reflect_with_coding_model

        coding = settings.config.coding
        model = coding.model or "claude-sonnet-4-5"
        return await reflect_with_coding_model(
            component_name,
            curr_param,
            side_info_text,
            run_id=run_id,
            provider=coding.provider,
            model=model,
        )

    return reflect
