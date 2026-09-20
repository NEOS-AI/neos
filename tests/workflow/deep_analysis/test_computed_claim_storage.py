"""계산 클레임이 행으로 남는가 (계약 §4, 마이그레이션 061).

**왜 이 파일이 필요한가.** J2 의 채점 규칙은 전부 `ProposedClaim` 위에서
돌았다. 그런데 클레임은 채점 전에 행이 되고(`_upsert_claim`), 행에 종류를
적을 자리가 없으면 계산 클레임은 **quote 로 저장된다.** 그 다음 계산이
그것을 전제로 삼으면 `E_COMPUTE_PREMISE_UNVERIFIED` 가 통과한다 -- 계약 §5
가 "verified **quote** 클레임" 이라고 적은 자리가 조용히 무너진다.

실제 DB 에 쓰고 각 테스트 끝에서 롤백한다.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    ComputedEvidence,
    ProposedClaim,
    Verdict,
    WorkerResult,
)

SCRIPT_REF = "f" * 16
INPUT_REF = "a" * 16


def _computation() -> ComputedEvidence:
    return ComputedEvidence(
        script_ref=SCRIPT_REF,
        inputs=[INPUT_REF],
        premises=["c1"],
        runtime={"profile": "research-offline-v1", "image_digest": "sha256:x"},
        output_digest="e" * 64,
        claimed_value="42.5",
    )


def _result(
    question_id: str, *claims: ProposedClaim, self_assessment: float = 0.8
) -> WorkerResult:
    return WorkerResult(
        question_id=question_id,
        status="completed",
        claims=list(claims),
        tokens_spent=0,
        self_assessment=self_assessment,
    )


async def _commit(session, *claims: ProposedClaim) -> str:
    run_id = await create_run(session, "root?", "dev")
    ledger = Ledger(session, run_id)
    question_id = await ledger.open_question(
        "q?", None, value_est=1.0, cap_tokens=2000, depth=0
    )
    await ledger._transition(question_id, "investigating")
    await ledger.commit_pass(
        question_id,
        _result(question_id, *claims),
        {claim.text: Verdict(ok=True) for claim in claims},
        judge_tokens_spent=0,
    )
    return run_id


async def _rows(session, run_id: str) -> list[tuple]:
    result = await session.execute(
        text(
            "SELECT text, kind, computation FROM deep_analysis_claims "
            "WHERE run_id=:run_id ORDER BY text"
        ),
        {"run_id": run_id},
    )
    return list(result)


@pytest.mark.asyncio
async def test_a_quote_claim_is_stored_as_a_quote_claim():
    """I1. 기존 경로는 컬럼이 생겨도 같은 행을 쓴다."""
    async with await db_manager.get_session() as session:
        run_id = await _commit(
            session, ProposedClaim(text="인용 클레임", confidence=0.5)
        )

        rows = await _rows(session, run_id)

        assert rows == [("인용 클레임", "quote", None)]
        await session.rollback()


@pytest.mark.asyncio
async def test_a_computed_claim_keeps_its_kind_and_its_computation():
    async with await db_manager.get_session() as session:
        run_id = await _commit(
            session,
            ProposedClaim(
                text="평균은 42.5 다",
                confidence=0.5,
                kind="computed",
                computation=_computation(),
            ),
        )

        (row,) = await _rows(session, run_id)

        assert row[1] == "computed"
        stored = json.loads(row[2])
        # 재현에 필요한 전부가 남아야 한다 (계약 §4) -- 하나라도 빠지면 그
        # 클레임은 다시 채점할 수 없고, 재개된 run 이 그것을 발견한다.
        assert stored["script_ref"] == SCRIPT_REF
        assert stored["inputs"] == [INPUT_REF]
        assert stored["premises"] == ["c1"]
        assert stored["output_digest"] == "e" * 64
        assert stored["claimed_value"] == "42.5"
        assert stored["runtime"]["profile"] == "research-offline-v1"
        await session.rollback()


@pytest.mark.asyncio
async def test_the_first_claim_of_a_text_decides_its_kind():
    """병합은 **신뢰도 상승**이지 재정의가 아니다.

    행의 정체성은 텍스트 해시다(D3). 같은 텍스트가 다른 종류로 다시 오면
    `_upsert_claim` 이 confidence 를 올리는데, 그때 종류까지 갈아치우면 이미
    그 행을 전제로 인용한 계산의 발밑이 바뀐다 -- `question_id` 와 `text` 를
    첫 기록대로 두는 것과 같은 이유다.
    """
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        question_id = await ledger.open_question(
            "q?", None, value_est=1.0, cap_tokens=2000, depth=0
        )
        quote = ProposedClaim(text="같은 문장", confidence=0.5)
        computed = ProposedClaim(
            text="같은 문장",
            confidence=0.5,
            kind="computed",
            computation=_computation(),
        )

        # 첫 패스는 자기평가를 낮게 둔다 -- 높으면 질문이 resolved 로 닫혀
        # 둘째 패스를 돌릴 수 없다(`test_ac_b_same_hash_merges...` 와 같다).
        for claim, assessment in ((quote, 0.2), (computed, 0.8)):
            await ledger._transition(question_id, "investigating")
            await ledger.commit_pass(
                question_id,
                _result(question_id, claim, self_assessment=assessment),
                {claim.text: Verdict(ok=True)},
                judge_tokens_spent=0,
            )

        rows = await _rows(session, run_id)

        assert len(rows) == 1
        assert rows[0][1] == "quote"
        assert rows[0][2] is None
        await session.rollback()


@pytest.mark.asyncio
async def test_a_stored_claim_reports_its_kind_to_the_grader():
    """채점기의 전제 검사가 읽는 자리다.

    `get_claim` 이 kind 를 싣지 않으면 계약 §5 의 "verified **quote**" 검사는
    쓸 수 있는 정보가 없다.
    """
    async with await db_manager.get_session() as session:
        run_id = await _commit(
            session,
            ProposedClaim(
                text="평균은 42.5 다",
                confidence=0.5,
                kind="computed",
                computation=_computation(),
            ),
        )
        ledger = Ledger(session, run_id)
        (row,) = await _rows(session, run_id)
        claim_id = await session.scalar(
            text(
                "SELECT id FROM deep_analysis_claims WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        )

        stored = await ledger.get_claim(claim_id)

        assert stored.kind == "computed"
        await session.rollback()
