"""Enqueue a GEPA opt job.

This module must not write the learned_lessons table. It does not add an HTTP route.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import shared_task

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

    store = GepaOptStore(resolve_lesson_session_factory())
    task_id = getattr(getattr(self, "request", None), "id", None) or "inline"
    return asyncio.run(
        execute_gepa_opt_job(
            store,
            run_id=run_id,
            owner_namespace=owner_namespace,
            celery_task_id=str(task_id),
        )
    )


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
    claimed = await store.claim(run_id, owner_namespace, celery_task_id)
    if not claimed:
        return "lost"
    evaluator = get_evaluator(surface)
    if evaluator is None:
        await store.fail_run(run_id, owner_namespace, "no_evaluator")
        return "no_evaluator"
    bundle = await store.load_bundle(run_id, owner_namespace)
    from neos.gepa_opt.engine import run_search
    from neos.gepa_opt.types import EngineConfig

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
        reflector=reflector if reflector is not None else _refuse_reflector,
    )
    if result.overlay is None:
        await store.fail_run(run_id, owner_namespace, result.error_code or "failed")
        return "failed"
    candidate_id = str(bundle["seed_candidate_id"])
    if result.overlay["components"] != bundle["seed"]:
        winner = next(
            row
            for row in reversed(result.candidates)
            if row["components"] == result.overlay["components"] and row["accepted"]
        )
        candidate_id = await store.commit_iteration(
            run_id=run_id,
            owner_namespace=owner_namespace,
            candidate={
                "iteration": winner["iteration"],
                "proposal_kind": winner["proposal_kind"],
                "components": winner["components"],
                "accepted": True,
                "val_mean": winner["val_mean"],
                "test_mean": winner.get("test_mean"),
            },
            scores=[],
            advance_cursor=True,
            best_candidate_id=None,
        )
    await store.stage_overlay(
        overlay_id=str(uuid.uuid4()),
        owner_namespace=owner_namespace,
        surface=bundle.get("surface") or surface,
        candidate_id=candidate_id,
        run_id=run_id,
    )
    await store.mark_succeeded(run_id, owner_namespace)
    return "staged"


async def _refuse_reflector(*_args: Any) -> Any:
    raise RuntimeError("gepa opt reflector is not configured")
