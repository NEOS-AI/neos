import pytest
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    WorkerResult,
    ProposedClaim,
    ProposedEvidence,
    RepairResult,
    Verdict,
)
from neos.database.connection import db_manager
import neos.database.models  # noqa: F401 - register FK targets
from sqlalchemy import text as sql


async def _investigating(led):
    qid = await led.open_question("q?", None, 1.0, 5000, 0)
    await led._transition(qid, "investigating")
    return qid


def _claim(text="fact", conf=0.6):
    return ProposedClaim(
        text=text,
        confidence=conf,
        evidence=[ProposedEvidence("http://x", "body", "hh")],
    )


async def _blob(s, run_id):
    await s.execute(
        sql(
            "INSERT INTO deep_analysis_blobs (run_id, content_hash, url, http_status, raw_text, fetched_at) "
            "VALUES (:r,'hh','http://x',200,'body',NOW()) ON CONFLICT DO NOTHING"
        ),
        {"r": run_id},
    )


@pytest.mark.asyncio
async def test_retry_cap_marks_unverified_after_two_rejections():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        led = Ledger(s, run_id)
        await _blob(s, run_id)
        # attempt 1 reject
        qid = await _investigating(led)
        await led.commit_pass(
            qid,
            WorkerResult(question_id=qid, status="completed", claims=[_claim()]),
            {"fact": Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")},
            judge_tokens_spent=0,
        )
        # attempt 2 reject (same hash) -> feedback attempt 2
        await led._transition(qid, "investigating")
        await led.commit_pass(
            qid,
            WorkerResult(question_id=qid, status="completed", claims=[_claim()]),
            {"fact": Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")},
            judge_tokens_spent=0,
        )
        # attempt 3 reject -> retry cap(2) hit -> unverified, no 3rd feedback
        await led._transition(qid, "investigating")
        await led.commit_pass(
            qid,
            WorkerResult(question_id=qid, status="completed", claims=[_claim()]),
            {"fact": Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")},
            judge_tokens_spent=0,
        )
        row = await s.execute(
            sql("SELECT status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id},
        )
        assert row.scalar() == "unverified"
        fb = await s.execute(
            sql("SELECT COUNT(*) FROM deep_analysis_feedback WHERE run_id=:r"),
            {"r": run_id},
        )
        assert fb.scalar() == 2  # capped at 2
        outcomes = (
            (
                await s.execute(
                    sql(
                        "SELECT payload::jsonb->>'outcome' FROM deep_analysis_events "
                        "WHERE run_id=:r AND kind='claim_graded' ORDER BY seq"
                    ),
                    {"r": run_id},
                )
            )
            .scalars()
            .all()
        )
        assert outcomes == ["rejected", "rejected", "unverified"]
        await s.rollback()


@pytest.mark.asyncio
async def test_retry_cap_resolves_pending_feedback():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        led = Ledger(s, run_id)
        await _blob(s, run_id)
        qid = await _investigating(led)
        # attempt 1 reject
        await led.commit_pass(
            qid,
            WorkerResult(question_id=qid, status="completed", claims=[_claim()]),
            {"fact": Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")},
            judge_tokens_spent=0,
        )
        # attempt 2 reject (same hash) -> feedback attempt 2
        await led._transition(qid, "investigating")
        await led.commit_pass(
            qid,
            WorkerResult(question_id=qid, status="completed", claims=[_claim()]),
            {"fact": Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")},
            judge_tokens_spent=0,
        )
        # attempt 3 reject -> retry cap(2) hit -> unverified, feedback must be resolved
        await led._transition(qid, "investigating")
        await led.commit_pass(
            qid,
            WorkerResult(question_id=qid, status="completed", claims=[_claim()]),
            {"fact": Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED")},
            judge_tokens_spent=0,
        )
        row = await s.execute(
            sql("SELECT status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id},
        )
        assert row.scalar() == "unverified"
        assert await led.pending_feedback(qid) == []
        await s.rollback()


@pytest.mark.asyncio
async def test_weaken_repair_replaces_text_and_resolves_feedback():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        led = Ledger(s, run_id)
        await _blob(s, run_id)
        qid = await _investigating(led)
        await led.commit_pass(
            qid,
            WorkerResult(
                question_id=qid, status="completed", claims=[_claim("overclaim")]
            ),
            {"overclaim": Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL")},
            judge_tokens_spent=0,
        )
        cid = (
            await s.execute(
                sql("SELECT id FROM deep_analysis_claims WHERE run_id=:r"),
                {"r": run_id},
            )
        ).scalar()
        await led._transition(qid, "investigating")
        rep = RepairResult(claim_id=cid, action="weakened", new_text="weaker claim")
        await led.commit_pass(
            qid, WorkerResult(question_id=qid, status="completed", repairs=[rep]), {},
            judge_tokens_spent=0,
        )
        row = await s.execute(
            sql("SELECT text, status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id},
        )
        txt, st = row.one()
        assert txt == "weaker claim" and st == "pending"
        rf = await s.execute(
            sql("SELECT resolved FROM deep_analysis_feedback WHERE run_id=:r"),
            {"r": run_id},
        )
        assert rf.scalar() == 1
        await s.rollback()


@pytest.mark.asyncio
async def test_regrade_claim_bills_judge_tokens():
    """C3-m1 Finding 3: a repaired claim pushed back to `pending` gets
    re-graded by `regrade_claim` (via `Orchestrator._regrade_pending`),
    outside of `commit_pass`. That re-grade can dispatch the agentic judge
    just like a fresh claim's grade does, but `regrade_claim` never billed
    `question.spent_tokens` at all -- a second unbilled path, same shape as
    the one `commit_pass` just closed.
    """
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        led = Ledger(s, run_id)
        await _blob(s, run_id)
        qid = await _investigating(led)
        await led.commit_pass(
            qid,
            WorkerResult(
                question_id=qid, status="completed", claims=[_claim("overclaim")]
            ),
            {"overclaim": Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL")},
            judge_tokens_spent=0,
        )
        cid = (
            await s.execute(
                sql("SELECT id FROM deep_analysis_claims WHERE run_id=:r"),
                {"r": run_id},
            )
        ).scalar()
        await led._transition(qid, "investigating")
        rep = RepairResult(claim_id=cid, action="weakened", new_text="weaker claim")
        await led.commit_pass(
            qid, WorkerResult(question_id=qid, status="completed", repairs=[rep]), {},
            judge_tokens_spent=0,
        )
        spent_before = (await led.get_question(qid)).spent_tokens

        verdict = Verdict(ok=True, tokens_spent=17, diagnostics={"judge_tokens": 17})
        await led.regrade_claim(qid, cid, verdict)

        q = await led.get_question(qid)
        assert q.spent_tokens == spent_before + 17
        await s.rollback()


@pytest.mark.asyncio
async def test_verified_pass_resets_fail_streak():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        led = Ledger(s, run_id)
        await _blob(s, run_id)
        qid = await _investigating(led)
        # a failed pass bumps streak
        await led.commit_pass(qid, WorkerResult(question_id=qid, status="failed"), {}, judge_tokens_spent=0)
        await led._transition(qid, "investigating")
        await led.commit_pass(
            qid,
            WorkerResult(
                question_id=qid,
                status="completed",
                claims=[_claim(conf=0.55)],
                self_assessment=0.9,
            ),
            {"fact": Verdict(ok=True)},
            judge_tokens_spent=0,
        )
        q = await led.get_question(qid)
        assert q.fail_streak == 0 and q.status == "resolved"
        await s.rollback()


@pytest.mark.asyncio
async def test_repair_converging_on_an_existing_claim_does_not_break_the_round():
    """실제 run을 죽인 회귀: repair가 run 안의 다른 클레임과 같은 텍스트로
    수렴하면 uq_deep_analysis_claims_run_hash를 위반해 **라운드 전체
    트랜잭션이 롤백**됐다.

    weaken은 문장을 더 일반적으로 만들기 때문에 서로 다른 클레임이 같은
    문장으로 수렴하는 일이 실제 LLM 출력에서 자연히 발생한다. 삽입 경로는
    hash 중복을 먼저 조회해 병합하지만 repair 경로에는 그 검사가 없었다.
    """
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        led = Ledger(s, run_id)
        await _blob(s, run_id)
        qid = await _investigating(led)

        # 클레임 둘: 하나는 거절돼 repair 대상, 하나는 살아남는다.
        await led.commit_pass(
            qid,
            WorkerResult(
                question_id=qid,
                status="completed",
                claims=[_claim("survivor"), _claim("doomed")],
            ),
            {
                "survivor": Verdict(ok=True),
                "doomed": Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL"),
            },
            judge_tokens_spent=0,
        )
        doomed_id = (
            await s.execute(
                sql(
                    "SELECT id FROM deep_analysis_claims "
                    "WHERE run_id=:r AND text='doomed'"
                ),
                {"r": run_id},
            )
        ).scalar()

        # repair가 살아있는 클레임과 같은 텍스트로 수렴한다.
        await led._transition(qid, "investigating")
        await led.commit_pass(
            qid,
            WorkerResult(
                question_id=qid,
                status="completed",
                repairs=[
                    RepairResult(
                        claim_id=doomed_id, action="weakened", new_text="survivor"
                    )
                ],
            ),
            {},
            judge_tokens_spent=0,
        )

        # 제약 위반 없이 진행되고, 중복 행이 생기지 않아야 한다.
        rows = (
            await s.execute(
                sql(
                    "SELECT hash, COUNT(*) FROM deep_analysis_claims "
                    "WHERE run_id=:r GROUP BY hash HAVING COUNT(*) > 1"
                ),
                {"r": run_id},
            )
        ).fetchall()
        assert rows == []

        # 수렴한 클레임은 재검증 대상이 아니다 -- 내용이 다른 행에 이미 있다.
        st = (
            await s.execute(
                sql("SELECT status FROM deep_analysis_claims WHERE id=:c"),
                {"c": doomed_id},
            )
        ).scalar()
        assert st == "unverified"
        await s.rollback()
