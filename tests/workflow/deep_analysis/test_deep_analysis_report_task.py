"""Tests for the periodic deep_analysis improvement-report task (L5)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.database.deep_analysis_models import DAReport
from neos.tasks.deep_analysis_report_task import _compute_report
from neos.workflow.deep_analysis.ledger import create_run


async def _ev(s, run_id, kind, payload="{}"):
    await s.execute(
        sql(
            "INSERT INTO deep_analysis_events (run_id, kind, qid, payload, ts) "
            "VALUES (:r,:k,NULL,:p,:ts)"
        ),
        {
            "r": run_id,
            "k": kind,
            "p": payload,
            "ts": datetime.now(timezone.utc).replace(tzinfo=None),
        },
    )


@pytest.mark.asyncio
async def test_compute_report_persists_signals_snapshot():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        await _ev(s, run_id, "claim_verified", '{"claim_id":"a"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_OVERCLAIM"}')
        await _ev(s, run_id, "pass_completed", '{"verified":3}')

        report = await _compute_report(s, window_days=7)

        stored = (
            await s.execute(select(DAReport).where(DAReport.id == report.id))
        ).scalar_one()
        assert stored.period_end > stored.period_start
        assert "totals" in stored.signals
        assert stored.signals["totals"]["claim_rejected"] >= 1
        assert stored.signals["reject_rate_by_code"]["E_OVERCLAIM"] > 0
        await s.rollback()


def test_report_task_registered_in_beat_schedule():
    from neos.workflow.celery_app import app

    entry = app.conf.beat_schedule.get("compute-deep-analysis-report")
    assert entry is not None
    assert entry["task"] == "neos.tasks.compute_deep_analysis_report"
