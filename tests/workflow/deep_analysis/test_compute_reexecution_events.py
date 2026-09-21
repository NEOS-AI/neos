"""재실행 사실이 원장에 닿는가 (계약 §6).

**왜 채점기가 아니라 원장이 내는가.** 계약은 두 이벤트의 payload 에
`claim_id` 를 요구한다. 그런데 채점이 도는 시점의 클레임은 아직 행이 아니라
`ProposedClaim` 이고 id 가 없다 -- id 는 `_apply_verdict` 가 판정을 행에
적용하는 순간에만 존재한다. 그래서 채점기는 **사실만** 진단에 싣고
(`test_computed_claim_grader.py`), 이벤트는 여기서 난다. 계약 §5 의 "재실행은
커밋 경로 밖에서 하고 **결과만 원장에 온다**" 와 같은 방향이다.

`test_ledger_report_body.py` 와 같은 규율을 따른다: 실제 DB 에 쓰고 각 테스트
끝에서 롤백한다.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    ProposedClaim,
    Verdict,
    WorkerResult,
)

CLAIM_TEXT = "평균은 42.5 다"


def _result(question_id: str) -> WorkerResult:
    """계산 클레임을 흉내 내되 **quote 로 싣는다**.

    `DAClaim` 에 아직 `kind` 컬럼이 없어 계산 클레임은 저장되지 않는다(J2 의
    마이그레이션 대기). 이 테스트가 고정하는 것은 저장이 아니라 **진단이
    이벤트로 바뀌는 길**이므로, 그 길은 클레임 종류와 무관하게 같다.
    """
    return WorkerResult(
        question_id=question_id,
        status="completed",
        claims=[ProposedClaim(text=CLAIM_TEXT, confidence=0.5)],
        tokens_spent=0,
        self_assessment=0.8,
    )


def _diagnostics(**overrides) -> dict:
    values = {
        "deterministic": "passed",
        "deterministic_code": "",
        "reexecuted": True,
        "reexec_matched": True,
        "reexec_capped": "",
        "reexec_duration_sec": 3.5,
    }
    values.update(overrides)
    return values


async def _commit(session, verdict: Verdict) -> tuple[str, str]:
    run_id = await create_run(session, "root?", "dev")
    ledger = Ledger(session, run_id)
    question_id = await ledger.open_question(
        "q?", None, value_est=1.0, cap_tokens=2000, depth=0
    )
    await ledger._transition(question_id, "investigating")
    await ledger.commit_pass(
        question_id,
        _result(question_id),
        {CLAIM_TEXT: verdict},
        judge_tokens_spent=0,
    )
    return run_id, question_id


async def _events(session, run_id: str, kind: str) -> list[dict]:
    rows = await session.execute(
        text(
            "SELECT qid, payload FROM deep_analysis_events "
            "WHERE run_id=:run_id AND kind=:kind ORDER BY seq"
        ),
        {"run_id": run_id, "kind": kind},
    )
    return [{"qid": qid, **json.loads(payload)} for qid, payload in rows]


@pytest.mark.asyncio
async def test_a_reproduced_computation_is_logged_with_its_claim_id():
    async with await db_manager.get_session() as session:
        run_id, question_id = await _commit(
            session, Verdict(ok=True, diagnostics=_diagnostics())
        )

        events = await _events(session, run_id, "compute_reexecuted")

        assert len(events) == 1
        assert events[0]["qid"] == question_id
        assert events[0]["matched"] is True
        assert events[0]["duration_sec"] == 3.5
        assert events[0]["claim_id"]
        await session.rollback()


@pytest.mark.asyncio
async def test_a_reproduction_failure_is_logged_as_run_but_unmatched():
    """거절돼도 **돌긴 돌았다**. 비용은 발생했고 원장은 그것을 알아야 한다."""
    async with await db_manager.get_session() as session:
        run_id, _ = await _commit(
            session,
            Verdict(
                ok=False,
                code="E_COMPUTE_NOT_REPRODUCED",
                diagnostics=_diagnostics(
                    deterministic="rejected",
                    deterministic_code="E_COMPUTE_NOT_REPRODUCED",
                    reexec_matched=False,
                ),
            ),
        )

        events = await _events(session, run_id, "compute_reexecuted")

        assert len(events) == 1
        assert events[0]["matched"] is False
        await session.rollback()


@pytest.mark.asyncio
async def test_a_capped_run_is_logged_as_a_cap_and_not_as_a_reexecution():
    """두 kind 를 나눈 이유가 여기 있다 (계약 §5).

    한도에 걸린 실행에는 "digest 일치 여부" 가 없다 -- 답을 내지 못했기
    때문이다. `compute_reexecuted` 에 `matched: false` 로 적으면 비용 사건이
    재현 실패로 집계된다.
    """
    async with await db_manager.get_session() as session:
        run_id, _ = await _commit(
            session,
            Verdict(
                ok=False,
                code="E_COMPUTE_CAPPED",
                diagnostics=_diagnostics(
                    deterministic="rejected",
                    deterministic_code="E_COMPUTE_CAPPED",
                    reexec_matched=None,
                    reexec_capped="cpu_sec",
                    reexec_duration_sec=30.0,
                ),
            ),
        )

        capped = await _events(session, run_id, "compute_reexecution_capped")

        assert len(capped) == 1
        assert capped[0]["limit"] == "cpu_sec"
        assert capped[0]["duration_sec"] == 30.0
        assert await _events(session, run_id, "compute_reexecuted") == []
        await session.rollback()


@pytest.mark.asyncio
async def test_a_quote_claim_logs_neither_event():
    """I1 의 자리다. 기존 경로의 판정에는 `reexec_*` 가 아예 없다."""
    async with await db_manager.get_session() as session:
        run_id, _ = await _commit(session, Verdict(ok=True))

        assert await _events(session, run_id, "compute_reexecuted") == []
        assert await _events(session, run_id, "compute_reexecution_capped") == []
        await session.rollback()


@pytest.mark.asyncio
async def test_a_computed_claim_that_never_ran_logs_neither_event():
    """규칙 1·2 에서 막힌 클레임. 샌드박스는 돌지 않았으므로 비용도 없다."""
    async with await db_manager.get_session() as session:
        run_id, _ = await _commit(
            session,
            Verdict(
                ok=False,
                code="E_COMPUTE_INPUT_UNFETCHED",
                diagnostics=_diagnostics(
                    deterministic="rejected",
                    deterministic_code="E_COMPUTE_INPUT_UNFETCHED",
                    reexecuted=False,
                    reexec_matched=None,
                    reexec_duration_sec=0.0,
                ),
            ),
        )

        assert await _events(session, run_id, "compute_reexecuted") == []
        assert await _events(session, run_id, "compute_reexecution_capped") == []
        await session.rollback()
