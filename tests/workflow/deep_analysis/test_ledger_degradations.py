"""강등 집계는 원장에서 읽는다 -- 새로고침 후 복원의 유일한 출처다.

test_ledger_report_body.py 와 같은 규율을 따른다: 실제 DB에 쓰고 각 테스트
끝에서 롤백한다. 남는 쓰기가 있으면 안 된다.

🔍 **정본 fixture 는 이제 이 파일에 없다** -- `tests/fixtures/`의 JSON 하나이고
프론트 테스트(`web/tests/source/deep-analysis-degradation.test.ts`)도 **같은
파일**을 읽는다. 판정 규칙은 여전히 두 언어에 각각 구현돼 있지만(설계 §3.3,
로드맵 §7 FE6), 어휘가 갈라지면 이제 반대쪽 테스트가 빨개진다.

예전에는 같은 목록이 두 파일에 손으로 복사돼 있었고 동기화를 강제하는 것은
주석뿐이었다. 트랙 E가 `projection.py` enum ↔ `types.ts` 유니온에 쓴 것과 같은
규율이며, 그때의 교훈(**대조 테스트 자체가 덜 검사할 수 있다**)에 따라 길이
단언을 함께 건다.
"""

import json
import pathlib

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "fixtures"
    / "deep_analysis_degradation_kinds.json"
)

# (kind, payload, 기대 결과 kind 또는 None)
CANONICAL_FIXTURE = [
    (case["kind"], case["payload"], case["resolved"])
    for case in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]
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


@pytest.mark.no_db
def test_the_shared_fixture_did_not_shrink():
    """대조 테스트가 덜 검사하는 사고에 대한 가드.

    트랙 E 에서 실제로 겪었다 -- `types.ts` 유니온을 파싱하는 정규식이 마지막
    멤버를 놓쳐 **조용히 6개만 비교**했다. fixture 를 파일로 옮기면 같은 종류의
    사고가 "파일은 읽었는데 케이스가 줄었다"의 모양으로 온다. 길이를 못박아
    두면 줄어든 순간 드러난다.

    양성 사례(강등으로 판정되는 것)와 음성 사례를 따로 센다: 음성만 남아도
    12개는 12개이기 때문이다.
    """
    resolved = [case for _, _, case in CANONICAL_FIXTURE if case is not None]
    ignored = [case for _, _, case in CANONICAL_FIXTURE if case is None]

    assert len(CANONICAL_FIXTURE) == 12
    assert len(resolved) == 6
    assert len(ignored) == 6
