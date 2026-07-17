import pytest
from sqlalchemy import text as sql

import neos.database.models  # noqa: F401 - register all FK targets on Base
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import WorkerResult, ProposedClaim, ProposedEvidence, ProposedBlob, Verdict
from neos.database.connection import db_manager


async def _run(s):
    return await create_run(s, "root?", "dev")


@pytest.mark.asyncio
async def test_gain_history_reads_verified_counts():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 5000, 0)
        # 두 번의 pass: 1개 verified, 0개 verified
        blob = ProposedBlob(content_hash="hh", source_url="http://x", http_status=200, raw_text="body fact text")
        ev = ProposedEvidence(source_url="http://x", excerpt="body fact text", raw_ref="hh")
        await led._transition(qid, "investigating")
        r1 = WorkerResult(question_id=qid, status="completed", blobs=[blob],
                          claims=[ProposedClaim(text="a fact", confidence=0.55, evidence=[ev])], tokens_spent=100)
        await led.commit_pass(qid, r1, {"a fact": Verdict(ok=True)})
        await led._transition(qid, "investigating")
        r2 = WorkerResult(question_id=qid, status="partial", tokens_spent=50)
        await led.commit_pass(qid, r2, {})
        hist = await led.gain_history(qid, last_n=3)
        assert hist[0] == 0 and hist[1] == 1   # 최신순
        await s.rollback()

@pytest.mark.asyncio
async def test_record_abandon_transitions_and_logs():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 0.1, 100, 4)
        await led.record_abandon(qid)
        q = await led.get_question(qid)
        assert q.status == "abandoned"
        row = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_events WHERE run_id=:r AND kind='abandoned'"), {"r": run_id})
        assert row.scalar() == 1
        await s.rollback()

@pytest.mark.asyncio
async def test_remaining_budget():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 1000, 0)
        await led._transition(qid, "investigating")
        await led.commit_pass(qid, WorkerResult(question_id=qid, status="partial", tokens_spent=300), {})
        assert await led.remaining_budget(qid) == 700
        await s.rollback()
