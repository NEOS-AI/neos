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
        await led.commit_pass(qid, r1, {"a fact": Verdict(ok=True)}, judge_tokens_spent=0)
        await led._transition(qid, "investigating")
        r2 = WorkerResult(question_id=qid, status="partial", tokens_spent=50)
        await led.commit_pass(qid, r2, {}, judge_tokens_spent=0)
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
        await led.commit_pass(qid, WorkerResult(question_id=qid, status="partial", tokens_spent=300), {}, judge_tokens_spent=0)
        assert await led.remaining_budget(qid) == 700
        await s.rollback()


# --- C3-m1: the judge's tokens now bill against the question, not just the
# worker's, via `commit_pass`'s `judge_tokens_spent` total. This is a
# ledger-level guarantee only: `commit_pass` adds the number it is given
# exactly once, regardless of how many claims (or repeated claim texts)
# `result` carries. It does NOT prove the *caller* computed that number
# correctly when a claim text repeats within a pass -- that is a dispatch-
# loop concern, covered by `test_duplicate_claim_text_does_not_drop_the_
# first_judges_tokens` in test_orchestrator_unit.py, since it requires
# driving `_grade()` twice for the same text and watching the `verdicts`
# dict overwrite, which is above the Ledger's abstraction level.


@pytest.mark.asyncio
async def test_commit_pass_refuses_to_guess_the_judges_spend():
    """C3-m2: 회계 인자에 기본값을 두지 않는다.

    기본값 0 은 지금은 무해하다 -- 프로덕션 호출부는 하나이고 항상 명시적으로
    넘긴다. 그러나 미래의 호출자가 빠뜨리면 **에러 없이 덜 청구된다.** 그것은
    C3-m1 이 방금 닫은 침묵 과소계상과 같은 모양이고, 같은 모양의 고장이
    §6 ③(가격 없는 모델이 비용을 0 으로 집계)에서 이미 한 번 났다.

    keyword-only 이기도 한 이유: 위치 인자로 남겨 두면 `verdicts` 다음에
    무엇이 오는지 호출부에서 안 보인다. 토큰 수와 dict 는 서로 섞여도
    타입 검사에 안 걸린다.
    """
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 5000, 0)
        await led._transition(qid, "investigating")
        result = WorkerResult(question_id=qid, status="partial", tokens_spent=10)

        with pytest.raises(TypeError):
            await led.commit_pass(qid, result, {})

        # 위치 인자로도 넘길 수 없다.
        with pytest.raises(TypeError):
            await led.commit_pass(qid, result, {}, 0)

        await s.rollback()


@pytest.mark.asyncio
async def test_commit_pass_bills_worker_and_judge_tokens():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 5000, 0)
        await led._transition(qid, "investigating")
        blob = ProposedBlob(content_hash="hh", source_url="http://x", http_status=200, raw_text="body fact text")
        ev = ProposedEvidence(source_url="http://x", excerpt="body fact text", raw_ref="hh")
        result = WorkerResult(
            question_id=qid,
            status="completed",
            blobs=[blob],
            claims=[ProposedClaim(text="a fact", confidence=0.55, evidence=[ev])],
            tokens_spent=100,  # worker's own search/entailment spend
        )
        verdict = Verdict(ok=True, tokens_spent=42, diagnostics={"judge_tokens": 42})
        await led.commit_pass(qid, result, {"a fact": verdict}, judge_tokens_spent=42)
        q = await led.get_question(qid)
        assert q.spent_tokens == 142  # 100 (worker) + 42 (judge), not either alone
        await s.rollback()


@pytest.mark.asyncio
async def test_commit_pass_bills_the_passed_total_exactly_once():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 5000, 0)
        await led._transition(qid, "investigating")
        blob = ProposedBlob(content_hash="hh", source_url="http://x", http_status=200, raw_text="body fact text")
        ev = ProposedEvidence(source_url="http://x", excerpt="body fact text", raw_ref="hh")
        # Same text twice in one pass -- _upsert_claim merges both into the
        # same DAClaim by hash, and `verdicts` (keyed by text) only ever has
        # one entry for it. `commit_pass` must not derive a token total from
        # that dict (it would only see the surviving Verdict once anyway) --
        # it must bill exactly the `judge_tokens_spent` it was given, once,
        # not once per claim in `result.claims`.
        claims = [
            ProposedClaim(text="a fact", confidence=0.55, evidence=[ev])
            for _ in range(2)
        ]
        result = WorkerResult(
            question_id=qid,
            status="completed",
            blobs=[blob],
            claims=claims,
            tokens_spent=100,
        )
        verdict = Verdict(ok=True, tokens_spent=42, diagnostics={"judge_tokens": 42})
        # The real, accumulated total across both (hypothetical) `_grade()`
        # dispatches -- what the orchestrator's loop would have computed.
        await led.commit_pass(
            qid, result, {"a fact": verdict}, judge_tokens_spent=64
        )
        q = await led.get_question(qid)
        assert q.spent_tokens == 164  # 100 + 64, not 100 + 42*2 and not 100 + 42
        await s.rollback()
