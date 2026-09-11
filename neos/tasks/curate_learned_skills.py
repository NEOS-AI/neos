"""Celery periodic task: prune/archive learned lessons. No LLM consolidate."""

from celery import shared_task

from neos.config.settings import get_settings
from neos.learn.curator import curate_lessons
from neos.learn.lessons import get_lesson_store
from neos.utils.logger import get_logger

logger = get_logger(__name__)


@shared_task(name="neos.tasks.curate_learned_skills")
def curate_learned_skills() -> dict[str, int]:
    """Daily prune/archive. Runs only when ``learn.curator`` is true."""
    settings = get_settings()
    learn = settings.config.learn
    if not learn.curator:
        logger.info("curate_learned_skills skipped: learn.curator is false")
        return {"archived": 0, "skipped": 0}
    result = curate_lessons(
        get_lesson_store(),
        stale_days=learn.stale_days,
        archive_days=learn.archive_days,
    )
    logger.info("curate_learned_skills finished: %s", result)
    return result
