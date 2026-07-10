import pytest
import neos.database.models  # noqa: F401 - register Base metadata
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.models import WorkerResult, ProposedClaim, ProposedEvidence, ProposedBlob, Verdict
from neos.workflow.deep_analysis.ledger import create_run
from neos.database.connection import db_manager
from sqlalchemy import text as sql

class OkGrader:
    async def grade(self, claim): return Verdict(ok=True)

@pytest.mark.asyncio
async def test_ac_b_cap_exhausted_question_splits():
    # 자식 cap을 작게 만들고, 워커가 cap 이상 토큰을 쓰게 해 다음 라운드 ladder가 SPLIT
    class Spender:
        async def investigate(self, b, e, qid, repairs=None):
            blob = ProposedBlob("hh","http://x",200,"body")
            ev = ProposedEvidence("http://x","body","hh")
            # confidence 낮게 유지해 resolved 전이를 막고 open 복귀 → 재선택 → cap 소진 판정
            return WorkerResult(question_id=qid, status="completed", blobs=[blob],
                                claims=[ProposedClaim("f", 0.3, [ev])], tokens_spent=100000,
                                self_assessment=0.1)
        def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        # 브리프 원안(단일 자식, cap=500000)과 달리 자식을 2개로 나눠 cap 수학을 맞춘다:
        # root 직계 자식 cap = global_token_cap // n_children. n_children=1이면 cap이 항상
        # global_token_cap과 같아져 "라운드1 소진 → 라운드2 SPLIT" 이전에 글로벌 캡이 먼저
        # should_stop을 True로 만들어버린다(SPLIT에 도달하지 못함). n_children=2, 정수 나눗셈
        # 버림을 이용해 global_token_cap=200001 → child_cap=100000(Spender의 라운드당 소비량과
        # 정확히 같음, ladder는 >=로 트립)로 두면: 라운드1 총 소비 200000 < 200001이라
        # should_stop이 아직 False → 라운드2 진입 → 두 자식 모두 spent(100000)>=cap(100000)
        # → SPLIT → depth2 손자 생성. 이 계산 덕에 ~3라운드로 끝나 <2s에 완료된다.
        orch = Orchestrator(s, run_id, lambda: Spender(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"s1","value_est":0.9},
                                                     {"text":"s2","value_est":0.9}],
                            global_token_cap=200001, max_depth=3)
        orch._split_decompose = (lambda text, *a: [{"text":"child","value_est":0.4}])
        await orch.run("root?")
        # 자식(depth1)이 cap 소진 후 SPLIT되어 손자(depth2) 생성
        row = await s.execute(sql("SELECT MAX(depth) FROM deep_analysis_questions WHERE run_id=:r"), {"r": run_id})
        assert row.scalar() >= 2
        # depth-2가 정말 cap 소진 -> SPLIT 경로에서 나왔는지: root 초기 split(1건) +
        # cap 소진으로 트립된 자식별 SPLIT(최소 1건, 최대 2건) = 최소 2건의 split 이벤트
        split_events = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_events WHERE run_id=:r AND kind='split'"), {"r": run_id})
        assert split_events.scalar() >= 2
        await s.rollback()
