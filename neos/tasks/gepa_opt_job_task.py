"""Enqueue a GEPA opt job.

This module must not write the learned_lessons table. It does not add an HTTP route.
"""

from __future__ import annotations

import asyncio

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
) -> str:
    """Lost claims return without writing. No evaluator fails the run."""
    claimed = await store.claim(run_id, owner_namespace, celery_task_id)
    if not claimed:
        return "lost"
    if get_evaluator(surface) is None:
        await store.fail_run(run_id, owner_namespace, "no_evaluator")
        return "no_evaluator"
    return "ready"
