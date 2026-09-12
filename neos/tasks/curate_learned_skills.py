"""Celery periodic task: prune/archive learned lessons. No LLM consolidate."""

import asyncio

from celery import shared_task

from neos.config.settings import get_settings
from neos.database.connection import DatabaseManager
from neos.learn.curator import curate_lessons_async
from neos.learn.lessons import resolve_lesson_session_factory, set_lesson_session_factory
from neos.learn.postgres import PostgresLessonStore
from neos.utils.logger import get_logger

logger = get_logger(__name__)


async def _curate_learned_skills(*, stale_days: int, archive_days: int) -> dict[str, int]:
    factory = resolve_lesson_session_factory()
    if factory is not None:
        return await curate_lessons_async(
            PostgresLessonStore(factory),
            stale_days=stale_days,
            archive_days=archive_days,
        )
    manager = DatabaseManager()
    try:
        await manager.initialize()
        set_lesson_session_factory(manager.get_session)
        return await curate_lessons_async(
            PostgresLessonStore(manager.get_session),
            stale_days=stale_days,
            archive_days=archive_days,
        )
    finally:
        set_lesson_session_factory(None)
        await manager.close()


@shared_task(name="neos.tasks.curate_learned_skills")
def curate_learned_skills() -> dict[str, int]:
    """Daily prune/archive. Runs only when ``learn.curator`` is true."""
    settings = get_settings()
    learn = settings.config.learn
    if not learn.curator:
        logger.info("curate_learned_skills skipped: learn.curator is false")
        return {"archived": 0, "skipped": 0}
    result = asyncio.run(
        _curate_learned_skills(
            stale_days=learn.stale_days,
            archive_days=learn.archive_days,
        )
    )
    logger.info("curate_learned_skills finished: %s", result)
    return result
