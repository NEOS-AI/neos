"""Deep Analysis L5 analytics API — on-demand improvement signals.

Read-only aggregation over the deep_analysis event log (Sub-project B).
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query

from neos.api.dependencies.auth import get_current_active_user
from neos.database.connection import db_manager
from neos.database.models import User
from neos.utils.logger import get_logger
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService

logger = get_logger(__name__)
router = APIRouter()

_PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}


@router.get("/deep-analysis/analytics")
async def get_deep_analysis_analytics(
    period: Literal["day", "week", "month", "all"] = Query(
        "week", description="Aggregation window for improvement signals."
    ),
    user: User = Depends(get_current_active_user),
) -> dict:
    """Return L5 improvement signals mined from the deep_analysis event log."""
    days = _PERIOD_DAYS[period]
    since = None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
    async with await db_manager.get_session() as session:
        service = DeepAnalysisAnalyticsService(session)
        summary = await service.summary(since=since)
    return {"period": period, **summary}
