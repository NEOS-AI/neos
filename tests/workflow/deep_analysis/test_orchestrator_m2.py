import asyncio, pytest
import neos.database.models  # noqa: F401 - register Base metadata
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.models import WorkerResult, ProposedClaim, ProposedEvidence, ProposedBlob, Verdict
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.database.connection import db_manager
from sqlalchemy import text as sql

class OkGrader:
    async def grade(self, claim): return Verdict(ok=True)

def _ok_result(qid, text="a fact"):
    blob = ProposedBlob(content_hash="hh", source_url="http://x", http_status=200, raw_text="body")
    ev = ProposedEvidence(source_url="http://x", excerpt="body", raw_ref="hh")
    return WorkerResult(question_id=qid, status="completed", blobs=[blob],
                        claims=[ProposedClaim(text=text, confidence=0.9, evidence=[ev])],
                        tokens_spent=100, self_assessment=0.9)

@pytest.mark.asyncio
async def test_ac_a_partial_claims_committed(monkeypatch):
    # 타임아웃 워커의 partial 클레임(+blob)이 커밋되는지
    from neos.workflow.deep_analysis import orchestrator as mod
    monkeypatch.setattr(mod, "_wall_clock_cap", lambda e: 0.05)
    class SlowPartial:
        def __init__(self): self._claims=[]; self._blobs=[ProposedBlob("hh","http://x",200,"body")]
        async def investigate(self, b, e, qid, repairs=None): await asyncio.sleep(10)
        def flush_partial(self, qid):
            return WorkerResult(question_id=qid, status="partial",
                                blobs=list(self._blobs), tokens_spent=10)
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        # 원래 5000 캡 + 10 토큰/라운드는 캡 소진까지 ~500라운드가 필요해 이 테스트만 ~82s가
        # 걸렸다(AC-a는 partial 커밋 여부만 증명하면 되고, 캡 소진까지 도는 라운드 수는 무관).
        # 15로 낮추면: 라운드1(breadth pass)에서 partial(10 토큰, blob 포함)이 커밋되어 이미
        # AC를 만족시키고, 라운드2(confidence<0.3 및 spent>0 → DIG)에서 다시 10토큰 소비해
        # 누적 20>=15가 되어 라운드3 진입 전 should_stop이 True로 정지한다. 즉 워커 호출은
        # 정확히 2회(둘 다 monkeypatch된 wall_clock_cap=0.05s로 즉시 타임아웃)뿐이라 수백 라운드
        # 스핀 없이 같은 AC(타임아웃→flush_partial→blob 커밋)를 훨씬 빠르게 증명한다.
        orch = Orchestrator(s, run_id, lambda: SlowPartial(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"sub","value_est":0.8}],
                            global_token_cap=15)
        await orch.run("root?")
        row = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_blobs WHERE run_id=:r"), {"r": run_id})
        assert row.scalar() >= 1   # partial blob 커밋됨
        await s.rollback()

@pytest.mark.asyncio
async def test_ac_c_fail_streak_forces_split():
    calls = {"n": 0}
    class Flaky:
        async def investigate(self, b, e, qid, repairs=None):
            calls["n"] += 1
            return WorkerResult(question_id=qid, status="failed", fail_reason="x")
        def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        # decompose로 자식 1개(depth1) → 실패 반복 → fail_streak 2 → SPLIT(자식 depth2)
        orch = Orchestrator(s, run_id, lambda: Flaky(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"sub","value_est":0.9}],
                            global_token_cap=5000, max_depth=3)
        # split이 일어나면 decompose가 다시 호출되어 자식 생성 → split 이벤트 존재
        async def split_decompose(text, *a): return [{"text":"child","value_est":0.5}]
        orch._split_decompose = split_decompose
        await orch.run("root?")
        row = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_events WHERE run_id=:r AND kind='split'"), {"r": run_id})
        assert row.scalar() >= 2   # root 초기 split + fail_streak 유발 split
        await s.rollback()

@pytest.mark.asyncio
async def test_ac_d_stops_at_global_cap():
    class Big:
        async def investigate(self, b, e, qid, repairs=None):
            r = _ok_result(qid); r.tokens_spent = 4000; return r
        def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(s, run_id, lambda: Big(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"s1","value_est":0.9},{"text":"s2","value_est":0.9}],
                            global_token_cap=5000)
        await orch.run("root?")
        total = await Ledger(s, run_id).total_spent()
        assert total >= 4000     # 캡 근처에서 정지(무한 루프 아님)
        await s.rollback()
