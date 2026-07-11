"""Celery periodic task: compute a rolling deep_analysis improvement report (L5).

Reads improvement signals from the append-only event log and persists a
snapshot to ``deep_analysis_reports``. The event log is never mutated.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from celery import shared_task

from neos.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 7


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _compute_report(session, *, window_days: int = DEFAULT_WINDOW_DAYS):
    """Compute signals over the rolling window and persist a DAReport.

    Returns the created ``DAReport``. Testable: pass a live session directly.
    """
    from neos.database.deep_analysis_models import DAReport
    from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService

    period_end = _naive_utc_now()
    period_start = period_end - timedelta(days=window_days)

    service = DeepAnalysisAnalyticsService(session)
    summary = await service.signals(since=period_start)

    report = DAReport(
        period_start=period_start,
        period_end=period_end,
        signals=summary,
    )
    session.add(report)
    await session.flush()
    return report


async def _compute_report_async() -> None:
    from neos.database.connection import get_session_ctx

    async with get_session_ctx() as session:
        report = await _compute_report(session)
        await session.commit()
        logger.info(
            "deep_analysis improvement report %s persisted (window %sd): %s",
            report.id,
            DEFAULT_WINDOW_DAYS,
            report.signals.get("totals", {}),
        )


@shared_task(
    name="neos.tasks.compute_deep_analysis_report",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def compute_deep_analysis_improvement_report(self):
    """Periodic (daily) rolling improvement-signal report. Registered in beat_schedule."""
    try:
        asyncio.run(_compute_report_async())
    except Exception as exc:  # noqa: BLE001
        logger.error("compute_deep_analysis_report failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)
