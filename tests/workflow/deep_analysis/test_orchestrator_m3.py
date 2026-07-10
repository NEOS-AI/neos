"""M3 Task 3: two-stage grading pipeline (deterministic -> agentic tier) +
question_id guard, exercised end-to-end through Orchestrator.run()."""

import pytest
from sqlalchemy import text as sql

import neos.database.models  # noqa: F401 - register Base metadata
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator


# --- fakes ---------------------------------------------------------------

class FakeDet:
    """Deterministic grader with a fixed ok/fail outcome; counts calls."""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    async def grade(self, claim):
        self.calls += 1
        if self.ok:
            return Verdict(ok=True)
        return Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")


class FakeAgentic:
    """Agentic tier returning a fixed verdict; counts calls to prove tiering."""

    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0
        self.seen_value_est = []

    async def grade(self, claim, value_est):
        self.calls += 1
        self.seen_value_est.append(value_est)
        return self.verdict


def _result(qid, tokens=5000):
    blob = ProposedBlob(content_hash="hh", source_url="http://x",
                        http_status=200, raw_text="body")
    ev = ProposedEvidence(source_url="http://x", excerpt="body", raw_ref="hh")
    return WorkerResult(
        question_id=qid,
        status="completed",
        blobs=[blob],
        claims=[ProposedClaim(text="fact", confidence=0.6, evidence=[ev])],
        tokens_spent=tokens,
        self_assessment=0.9,
    )


class FixedWorker:
    """Returns the same well-formed result for whatever question it is given."""

    async def investigate(self, brief, effort, qid):
        return _result(qid)

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


class MismatchThenFixWorker:
    """First investigation returns a bogus question_id (mismatch); later
    investigations behave correctly. Shared state across fresh instances."""

    def __init__(self, state):
        self.state = state

    async def investigate(self, brief, effort, qid):
        self.state["n"] += 1
        if self.state["n"] == 1:
            return _result("ZZZZZZZZ")  # wrong question_id
        return _result(qid)

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


def _decompose_one(_root):
    return [{"text": "sub", "value_est": 0.9}]


async def _build(session, run_id, worker_factory, det, agentic):
    return Orchestrator(
        session,
        run_id,
        worker_factory=worker_factory,
        grader=det,
        agentic_grader=agentic,
        decompose_fn=_decompose_one,
        global_token_cap=5000,
    )


# --- tests ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_det_fail_short_circuits_agentic_and_commits_rejected():
    det = FakeDet(ok=False)
    agentic = FakeAgentic(Verdict(ok=True, label="SUPPORTS"))
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = await _build(s, run_id, lambda: FixedWorker(), det, agentic)
        await orch.run("root?")
        status = (await s.execute(
            sql("SELECT status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert status == "rejected"
        assert agentic.calls == 0  # det failure never reaches agentic tier
        await s.rollback()


@pytest.mark.asyncio
async def test_det_ok_agentic_partial_rejects_with_feedback():
    det = FakeDet(ok=True)
    agentic = FakeAgentic(
        Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL", detail="too broad"))
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = await _build(s, run_id, lambda: FixedWorker(), det, agentic)
        await orch.run("root?")
        status = (await s.execute(
            sql("SELECT status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert status == "rejected"
        assert agentic.calls == 1
        fb = (await s.execute(
            sql("SELECT code FROM deep_analysis_feedback WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert fb == "E_OVERCLAIM"
        await s.rollback()


@pytest.mark.asyncio
async def test_det_ok_agentic_supports_verifies():
    det = FakeDet(ok=True)
    agentic = FakeAgentic(Verdict(ok=True, label="SUPPORTS"))
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = await _build(s, run_id, lambda: FixedWorker(), det, agentic)
        await orch.run("root?")
        rows = dict((await s.execute(
            sql("SELECT status, COUNT(*) FROM deep_analysis_claims "
                "WHERE run_id=:r GROUP BY status"),
            {"r": run_id})).all())
        assert rows.get("verified") == 1
        assert agentic.calls == 1
        # value_est threaded from the question row (stored as REAL/float32)
        assert agentic.seen_value_est == pytest.approx([0.9], abs=1e-6)
        sub = (await s.execute(
            sql("SELECT status FROM deep_analysis_questions "
                "WHERE run_id=:r AND text='sub'"),
            {"r": run_id})).scalar()
        assert sub == "resolved"
        await s.rollback()


@pytest.mark.asyncio
async def test_question_id_mismatch_skips_and_returns_question_to_open():
    det = FakeDet(ok=True)
    agentic = FakeAgentic(Verdict(ok=True, label="SUPPORTS"))
    state = {"n": 0}
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = await _build(
            s, run_id, lambda: MismatchThenFixWorker(state), det, agentic)
        await orch.run("root?")
        # a mismatch was detected and logged
        mismatches = (await s.execute(
            sql("SELECT COUNT(*) FROM deep_analysis_events "
                "WHERE run_id=:r AND kind='worker_result_mismatch'"),
            {"r": run_id})).scalar()
        assert mismatches == 1
        # the original question was NOT left stuck in investigating: it went
        # back to open, got re-selected, and finally resolved.
        sub = (await s.execute(
            sql("SELECT status FROM deep_analysis_questions "
                "WHERE run_id=:r AND text='sub'"),
            {"r": run_id})).scalar()
        assert sub == "resolved"
        # the bogus result never committed a claim
        claim_count = (await s.execute(
            sql("SELECT COUNT(*) FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert claim_count == 1  # only the second (valid) pass committed
        await s.rollback()
