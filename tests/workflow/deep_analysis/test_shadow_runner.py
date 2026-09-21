"""J3 를 실제로 돌리는 자리 (로드맵 J3).

앞의 세 조각 -- 섀도 원장·blob 보관소·비교 -- 은 각자 초록이었지만 서로를
부르지 않았다. 이 파일이 그 셋을 한 호출로 꿴다. **부르는 곳이 없는 코드는
동작한다고 말할 수 없다**는 것이 이 저장소가 K2b 에서 배운 것이다.

`run_offline_shadow` 가 `Assignment` 를 **인자로 받는** 것이 설계다. 끝난
run 에서 brief 를 되짚는 것은 그 자체로 추측이고, 추측한 brief 를 워커에게
주면 워커가 본 것이 프로덕션과 달라진다 -- 그러면 비교는 두 워커가 아니라
두 프롬프트를 비교한 것이 된다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    Assignment,
    Effort,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)

URL = "https://example.com/a"
BODY = "MoE routing lowers cost"


def _blob() -> ProposedBlob:
    from neos.workflow.deep_analysis.fetch import _blob_hash

    return ProposedBlob(
        content_hash=_blob_hash(BODY, URL, 200),
        source_url=URL,
        http_status=200,
        raw_text=BODY,
    )


async def _recorded_run(session) -> tuple[Ledger, str]:
    """옛 워커가 클레임 하나를 남기고 끝낸 run."""
    run_id = await create_run(session, "root?", "dev")
    ledger = Ledger(session, run_id)
    question_id = await ledger.open_question(
        "MoE 라우팅은 비용을 낮추는가?",
        None,
        value_est=1.0,
        cap_tokens=2000,
        depth=0,
    )
    await ledger._transition(question_id, "investigating")
    blob = _blob()
    claim = ProposedClaim(
        text=BODY,
        confidence=0.5,
        evidence=[
            ProposedEvidence(source_url=URL, excerpt=BODY, raw_ref=blob.content_hash)
        ],
    )
    await ledger.commit_pass(
        question_id,
        WorkerResult(
            question_id=question_id,
            status="completed",
            blobs=[blob],
            claims=[claim],
            tokens_spent=100,
            self_assessment=0.8,
        ),
        {BODY: Verdict(ok=True)},
        judge_tokens_spent=0,
    )
    return ledger, question_id


def _assignment(question_id: str) -> Assignment:
    return Assignment(
        question_id=question_id,
        brief="브리프",
        effort=Effort.DIG,
        question_text="MoE 라우팅은 비용을 낮추는가?",
    )


class _Sandbox:
    async def materialize_evidence(self, raw_ref: str, text: str) -> str:
        return f"/evidence/{raw_ref}.txt"


def _worker(claims: list[str], *, fetches: list[str] = ()):
    """조사 워커 자리 -- **진짜 도구 포트**를 쓴다.

    가짜가 `fetch_fn` 만 직접 부르면 원장 쓰기 경로를 한 줄도 타지 않고,
    그러면 "섀도는 아무것도 쓰지 않는다" 는 테스트가 **공허하게** 통과한다.
    막으려는 쓰기가 실제로 시도돼야 막았다고 말할 수 있다.
    """

    async def run(assignment, *, ledger, fetch_fn):
        from neos.workflow.deep_analysis.evidence_store import LedgerEvidenceStore
        from neos.workflow.deep_analysis.research_tools import ResearchToolPort

        port = ResearchToolPort(
            fetch_fn=fetch_fn,
            store=LedgerEvidenceStore(ledger, question_id=assignment.question_id),
            sandbox=_Sandbox(),
            cap_bytes=1024 * 1024,
        )
        for url in fetches:
            await port.execute("fetch.v1", {"url": url})
        return WorkerResult(
            question_id=assignment.question_id,
            status="completed",
            claims=[ProposedClaim(text=text, confidence=0.5) for text in claims],
        )

    return run


async def _shadow(session, ledger, question_id, worker):
    from neos.workflow.deep_analysis.shadow import run_offline_shadow

    return await run_offline_shadow(
        ledger,
        _assignment(question_id),
        worker=worker,
    )


@pytest.mark.asyncio
async def test_the_shadow_reproduces_the_recorded_claim():
    """같은 증거로 같은 결론에 닿으면 갈래는 `shared` 하나다."""
    async with await db_manager.get_session() as session:
        ledger, question_id = await _recorded_run(session)

        result = await _shadow(
            session, ledger, question_id, _worker([BODY], fetches=[URL])
        )

        assert result.shared == (BODY,)
        assert result.only_recorded == ()
        assert result.served_urls == (URL,)
        assert result.evidence_was_complete is True
        await session.rollback()


@pytest.mark.asyncio
async def test_a_url_outside_the_archive_is_counted_not_faked():
    async with await db_manager.get_session() as session:
        ledger, question_id = await _recorded_run(session)

        result = await _shadow(
            session,
            ledger,
            question_id,
            _worker([BODY], fetches=[URL, "https://example.com/새것"]),
        )

        assert result.missed_urls == ("https://example.com/새것",)
        assert result.evidence_was_complete is False
        await session.rollback()


@pytest.mark.asyncio
async def test_a_claim_the_shadow_missed_keeps_its_recorded_status():
    async with await db_manager.get_session() as session:
        ledger, question_id = await _recorded_run(session)

        result = await _shadow(session, ledger, question_id, _worker([]))

        assert [(c.text, c.status) for c in result.only_recorded] == [
            (BODY, "verified")
        ]
        await session.rollback()


@pytest.mark.asyncio
async def test_the_shadow_writes_nothing_to_the_run_it_shadows():
    """J3 의 계약 그 자체다.

    섀도가 쓰면 기록된 run 이 더 이상 비교 **대상**이 아니게 된다 -- 두 번째
    섀도는 첫 번째가 남긴 것 위에서 돈다.
    """
    async with await db_manager.get_session() as session:
        ledger, question_id = await _recorded_run(session)
        before = await _snapshot(session, ledger.run_id)

        await _shadow(
            session,
            ledger,
            question_id,
            _worker(["섀도가 새로 낸 클레임"], fetches=[URL]),
        )
        await session.flush()

        assert await _snapshot(session, ledger.run_id) == before
        await session.rollback()


async def _snapshot(session, run_id: str) -> tuple:
    claims = await session.scalar(
        text("SELECT COUNT(*) FROM deep_analysis_claims WHERE run_id=:r"),
        {"r": run_id},
    )
    blobs = await session.scalar(
        text("SELECT COUNT(*) FROM deep_analysis_blobs WHERE run_id=:r"),
        {"r": run_id},
    )
    events = await session.scalar(
        text("SELECT COUNT(*) FROM deep_analysis_events WHERE run_id=:r"),
        {"r": run_id},
    )
    spent = await session.scalar(
        text("SELECT evidence_bytes FROM deep_analysis_questions WHERE run_id=:r"),
        {"r": run_id},
    )
    return (int(claims), int(blobs), int(events), int(spent))
