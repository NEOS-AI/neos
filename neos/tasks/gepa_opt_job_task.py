"""Enqueue a GEPA opt job. The search itself is a later slice.

This module must not write the learned_lessons table.
"""

from celery import shared_task

from neos.config.settings import settings


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
def run_gepa_opt_job(self, run_id: str, owner_namespace: str) -> None:
    """Worker entry. Search is not implemented in this slice."""
    raise NotImplementedError(
        f"gepa opt search is not implemented for {run_id} in {owner_namespace}"
    )
