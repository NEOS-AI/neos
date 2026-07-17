"""Tests for the DAReport model / deep_analysis_reports table (L5)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.database.deep_analysis_models import DAReport


def test_dareport_tablename_and_columns():
    assert DAReport.__tablename__ == "deep_analysis_reports"
    cols = {c.name for c in DAReport.__table__.columns}
    assert {"id", "period_start", "period_end", "signals", "created_at"} <= cols


@pytest.mark.asyncio
async def test_dareport_roundtrip_persists_signals_json():
    async with await db_manager.get_session() as s:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        report = DAReport(
            period_start=now - timedelta(days=7),
            period_end=now,
            signals={"overclaim_rate": 0.25, "totals": {"claim_rejected": 4}},
        )
        s.add(report)
        await s.flush()

        stored = (
            await s.execute(select(DAReport).where(DAReport.id == report.id))
        ).scalar_one()
        assert stored.signals["overclaim_rate"] == 0.25
        assert stored.signals["totals"]["claim_rejected"] == 4
        await s.rollback()
