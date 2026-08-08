"""강등 집계는 원장에서 읽는다 -- 새로고침 후 복원의 유일한 출처다.

test_ledger_report_body.py 와 같은 규율을 따른다: 실제 DB에 쓰고 각 테스트
끝에서 롤백한다. 남는 쓰기가 있으면 안 된다.

⚠️ 🟡 이 파일의 CANONICAL_FIXTURE 는 **정본 fixture 목록**이다. 같은 목록이
`web/tests/source/deep-analysis-degradation.test.ts` 에도 있다. 강등 어휘를
바꾸면 **반드시 양쪽을 함께** 고칠 것 -- 규칙이 두 언어로 구현돼 있기 때문이다
(설계 §3.3, 로드맵 §7 FE6).
"""

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run

# (kind, payload, 기대 결과 kind 또는 None)
CANONICAL_FIXTURE = [
    ("report_assembly_degraded", {"reason": "token_budget_exhausted"},
     "report_assembly_degraded"),
    ("node_reduction_degraded", {"reason": "token_budget_exhausted"},
     "node_reduction_degraded"),
    ("finalization_prompt_clamped", {"exhausted": True, "stage": "report_assembly"},
     "finalization_prompt_clamped"),
    ("finalization_prompt_clamped", {"exhausted": False, "stage": "report_assembly"},
     None),
    ("report_graded", {"ok": True, "judge": "budget_exhausted"},
     "judge_unreviewed:budget_exhausted"),
    ("report_graded", {"ok": True, "judge": "truncated"},
     "judge_unreviewed:truncated"),
    ("report_graded", {"ok": True, "judge": "unparseable"},
     "judge_unreviewed:unparseable"),
    ("report_graded", {"ok": True, "uncited_ratio": 0.1}, None),
    ("investigation_stopped_at_floor", {"floor_tokens": 41040}, None),
    ("investigation_stopped_at_input_bound",
     {"stage": "worker_analysis", "input_bound": 17723, "ceiling": 12000}, None),
    ("claim_discarded", {}, None),
    ("llm_truncated", {"stage": "worker_analysis"}, None),
]


@pytest.mark.asyncio
async def test_degradations_counts_the_canonical_fixture():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        for kind, payload, _ in CANONICAL_FIXTURE:
            await ledger.log(kind, None, payload)

        expected: list[dict[str, object]] = []
        for _, _, resolved in CANONICAL_FIXTURE:
            if resolved is None:
                continue
            existing = next(
                (e for e in expected if e["kind"] == resolved), None
            )
            if existing is None:
                expected.append({"kind": resolved, "count": 1})
            else:
                existing["count"] = int(existing["count"]) + 1

        assert await ledger.degradations() == expected
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_sums_repeats_and_keeps_first_seen_order():
    """3회와 1회는 다른 이야기다. 순서는 최초 발생 순."""
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        await ledger.log("node_reduction_degraded", None, {})
        await ledger.log("report_assembly_degraded", None, {})
        await ledger.log("node_reduction_degraded", None, {})

        assert await ledger.degradations() == [
            {"kind": "node_reduction_degraded", "count": 2},
            {"kind": "report_assembly_degraded", "count": 1},
        ]
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_is_empty_when_nothing_was_degraded():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log("job_started", None, {"profile": "dev"})

        assert await Ledger(s, run_id).degradations() == []
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_ignores_other_runs():
    """집계는 run 단위다. 다른 run의 강등이 새면 사용자에게 남의 경고가 뜬다."""
    async with await db_manager.get_session() as s:
        mine = await create_run(s, "내 질문", "dev")
        theirs = await create_run(s, "남 질문", "dev")
        await Ledger(s, theirs).log("report_assembly_degraded", None, {})

        assert await Ledger(s, mine).degradations() == []
        await s.rollback()


@pytest.mark.asyncio
async def test_degradations_survives_a_malformed_payload():
    """방어적으로 읽는다 -- 페이로드 모양이 바뀌어도 예외를 내지 않는다."""
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        await ledger.log("report_graded", None, {"judge": 42})
        await ledger.log("report_graded", None, {"judge": ""})
        await ledger.log("finalization_prompt_clamped", None, {"exhausted": "yes"})

        assert await ledger.degradations() == []
        await s.rollback()
