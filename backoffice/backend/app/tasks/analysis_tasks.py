"""Celery tasks for analysis pipeline execution."""

import asyncio
import logging
from typing import Optional

from app.core.database import get_db_context
from app.services.analysis_service import AnalysisService
from app.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="run_analysis_pipeline")
def run_analysis_pipeline(
    self,
    run_id: str,
    use_llm_extraction: bool = True,
) -> dict:
    """Execute the full analysis pipeline.

    Args:
        run_id: ID of the analysis run.
        use_llm_extraction: Whether to use LLM for facet extraction.

    Returns:
        Result dictionary with status and statistics.
    """
    logger.info(f"Starting analysis pipeline for run_id={run_id}")

    async def _run():
        async with get_db_context() as db:
            service = AnalysisService(db)
            run = await service.run_analysis(
                run_id=run_id,
                use_llm_extraction=use_llm_extraction,
            )
            return {
                "run_id": run.run_id,
                "status": run.status,
                "total_conversations": run.total_conversations,
                "total_clusters": run.total_clusters,
            }

    try:
        result = asyncio.run(_run())
        logger.info(f"Analysis pipeline completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Analysis pipeline failed: {e}")
        raise


@celery_app.task(bind=True, name="run_incremental_analysis")
def run_incremental_analysis(
    self,
    run_id: str,
    since_conversation_id: Optional[int] = None,
) -> dict:
    """Run incremental analysis on new conversations.

    Args:
        run_id: ID of the analysis run to update.
        since_conversation_id: Only process conversations after this ID.

    Returns:
        Result dictionary.
    """
    logger.info(f"Starting incremental analysis for run_id={run_id}")

    # TODO: Implement incremental analysis
    return {"status": "not_implemented"}


@celery_app.task(bind=True, name="rebuild_cluster_hierarchy")
def rebuild_cluster_hierarchy(self, run_id: str) -> dict:
    """Rebuild cluster hierarchy for an existing analysis.

    Args:
        run_id: ID of the analysis run.

    Returns:
        Result dictionary.
    """
    logger.info(f"Rebuilding cluster hierarchy for run_id={run_id}")

    # TODO: Implement hierarchy rebuild
    return {"status": "not_implemented"}


@celery_app.task(name="cleanup_old_analysis_runs")
def cleanup_old_analysis_runs(max_age_days: int = 90) -> dict:
    """Clean up old analysis runs.

    Args:
        max_age_days: Delete runs older than this many days.

    Returns:
        Result with count of deleted runs.
    """
    logger.info(f"Cleaning up analysis runs older than {max_age_days} days")

    # TODO: Implement cleanup
    return {"deleted_count": 0}
