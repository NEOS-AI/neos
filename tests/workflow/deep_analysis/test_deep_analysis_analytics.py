"""DB-backed tests for DeepAnalysisAnalyticsService.

Seeds raw events into the append-only ``deep_analysis_events`` log and
asserts the derived improvement signals. All assertions roll back at the
end -- this service (and these tests) must never leave writes behind.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text as sql

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService
from neos.workflow.deep_analysis.ledger import create_run


def _naive_utc(value: datetime) -> datetime:
    # deep_analysis_events.ts is ``timestamp without time zone`` (naive UTC),
    # and the test schema has no server DEFAULT on it (the ORM default is
    # Python-side only), so raw inserts must supply ts explicitly.
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


async def _ev(s, run_id, kind, payload="{}"):
    await s.execute(
        sql(
            "INSERT INTO deep_analysis_events (run_id, kind, qid, payload, ts) "
            "VALUES (:r,:k,NULL,:p,:ts)"
        ),
        {"r": run_id, "k": kind, "p": payload,
         "ts": _naive_utc(datetime.now(timezone.utc))},
    )


async def _ev_at(s, run_id, kind, ts, payload="{}"):
    await s.execute(
        sql(
            "INSERT INTO deep_analysis_events (run_id, kind, qid, payload, ts) "
            "VALUES (:r,:k,NULL,:p,:ts)"
        ),
        {"r": run_id, "k": kind, "p": payload, "ts": _naive_utc(ts)},
    )


@pytest.mark.asyncio
async def test_signals_run_id_excludes_other_runs():
    async with await db_manager.get_session() as s:
        selected_run = await create_run(s, "selected", "dev")
        other_run = await create_run(s, "other", "dev")
        await _ev(s, selected_run, "claim_verified")
        await _ev(s, other_run, "claim_rejected", '{"code":"E_OVERCLAIM"}')

        sig = await DeepAnalysisAnalyticsService(s).signals(run_id=selected_run)

        assert sig["totals"] == {"claim_verified": 1}
        assert sig["reject_rate_by_code"] == {}
        await s.rollback()


@pytest.mark.asyncio
async def test_signals_without_run_id_remains_global():
    async with await db_manager.get_session() as s:
        first_run = await create_run(s, "first-global", "dev")
        second_run = await create_run(s, "second-global", "dev")
        future = datetime.now(timezone.utc) + timedelta(days=3650)
        await _ev_at(s, first_run, "claim_verified", future)
        await _ev_at(s, second_run, "claim_verified", future)

        sig = await DeepAnalysisAnalyticsService(s).signals(
            since=future - timedelta(seconds=1)
        )

        assert sig["totals"]["claim_verified"] == 2
        await s.rollback()


@pytest.mark.asyncio
async def test_signals_compute_from_events():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        await _ev(s, run_id, "claim_verified", '{"claim_id":"a"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_OVERCLAIM"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_UNSUPPORTED"}')
        await _ev(s, run_id, "claim_unverified", '{"code":"E_UNSUPPORTED"}')
        await _ev(s, run_id, "pass_completed", '{"verified":2}')
        await _ev(s, run_id, "pass_completed", '{"verified":0}')
        await _ev(s, run_id, "report_graded", '{"ok":false,"code":"E_ORPHAN_CITE"}')
        await _ev(s, run_id, "report_graded", '{"ok":true}')
        svc = DeepAnalysisAnalyticsService(s)
        sig = await svc.signals(run_id=run_id)
        assert sig["reject_rate_by_code"]["E_OVERCLAIM"] > 0
        assert abs(sig["avg_verified_per_pass"] - 1.0) < 1e-6
        assert abs(sig["report_retry_rate"] - 0.5) < 1e-6
        assert sig["unverified_rate"] > 0
        await s.rollback()


@pytest.mark.asyncio
async def test_signals_reject_rate_overclaim_and_reinvestigation():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        await _ev(s, run_id, "claim_rejected", '{"code":"E_OVERCLAIM"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_OVERCLAIM"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_CONFIDENCE_INFLATED"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_UNSUPPORTED"}')
        await _ev(s, run_id, "dead_end", '{"text":"nope"}')
        await _ev(s, run_id, "dead_end", '{"text":"nope2"}')
        await _ev(s, run_id, "question_opened", '{"depth":0,"value_est":1.0}')
        await _ev(s, run_id, "question_opened", '{"depth":1,"value_est":0.5}')
        await _ev(s, run_id, "conflict_reinvestigation", '{"qids":["q1"]}')
        await _ev(s, run_id, "conflict_reinvestigation", '{"qids":["q2"]}')

        svc = DeepAnalysisAnalyticsService(s)
        sig = await svc.signals(run_id=run_id)

        assert abs(sig["reject_rate_by_code"]["E_OVERCLAIM"] - 0.5) < 1e-6
        assert abs(sig["reject_rate_by_code"]["E_CONFIDENCE_INFLATED"] - 0.25) < 1e-6
        assert abs(sig["reject_rate_by_code"]["E_UNSUPPORTED"] - 0.25) < 1e-6
        assert abs(sig["overclaim_rate"] - 0.75) < 1e-6
        assert abs(sig["dead_end_rate"] - 1.0) < 1e-6
        assert sig["reinvestigation_count"] == 2
        assert sig["totals"]["claim_rejected"] == 4
        assert sig["totals"]["dead_end"] == 2
        assert sig["totals"]["question_opened"] == 2
        assert sig["totals"]["conflict_reinvestigation"] == 2
        await s.rollback()


@pytest.mark.asyncio
async def test_signals_malformed_payload_does_not_crash():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        await _ev(s, run_id, "claim_rejected", "not-json")
        await _ev(s, run_id, "claim_rejected", '{"code":"E_OVERCLAIM"}')
        await _ev(s, run_id, "pass_completed", "{broken")
        await _ev(s, run_id, "pass_completed", '{"verified":4}')

        svc = DeepAnalysisAnalyticsService(s)
        sig = await svc.signals(run_id=run_id)

        # malformed events still count toward totals / denominators...
        assert sig["totals"]["claim_rejected"] == 2
        assert sig["totals"]["pass_completed"] == 2
        # ...but don't poison numeric aggregates: only the well-formed
        # pass_completed row contributes to the average.
        assert abs(sig["avg_verified_per_pass"] - 4.0) < 1e-6
        # only the well-formed claim_rejected row has a usable code.
        assert sig["reject_rate_by_code"]["E_OVERCLAIM"] == 0.5
        await s.rollback()


@pytest.mark.asyncio
async def test_signals_since_filters_old_events():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        old_ts = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        await _ev_at(s, run_id, "claim_verified", old_ts, '{"claim_id":"old"}')
        await _ev(s, run_id, "claim_verified", '{"claim_id":"new"}')

        svc = DeepAnalysisAnalyticsService(s)
        sig = await svc.signals(since=cutoff, run_id=run_id)

        assert sig["totals"]["claim_verified"] == 1
        await s.rollback()


@pytest.mark.asyncio
async def test_signals_empty_log_has_zero_rates_not_errors():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "empty", "dev")
        svc = DeepAnalysisAnalyticsService(s)
        sig = await svc.signals(run_id=run_id)

        assert sig["overclaim_rate"] == 0.0
        assert sig["dead_end_rate"] == 0.0
        assert sig["unverified_rate"] == 0.0
        assert sig["avg_verified_per_pass"] == 0.0
        assert sig["report_retry_rate"] == 0.0
        assert sig["reinvestigation_count"] == 0
        assert sig["reject_rate_by_code"] == {}
        assert sig["totals"] == {}
        await s.rollback()


@pytest.mark.asyncio
async def test_summary_includes_signals_and_period_metadata():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        await _ev(s, run_id, "claim_verified", '{"claim_id":"a"}')
        since = datetime.now(timezone.utc) - timedelta(hours=1)

        svc = DeepAnalysisAnalyticsService(s)
        result = await svc.summary(since=since, run_id=run_id)

        assert "signals" in result
        assert result["signals"]["totals"] == {"claim_verified": 1}
        assert result["since"] == since
        assert isinstance(result["generated_at"], datetime)
        await s.rollback()
