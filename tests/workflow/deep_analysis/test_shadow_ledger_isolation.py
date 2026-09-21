"""섀도가 **진짜 DB** 를 건드리지 않는가 (로드맵 J3).

`test_shadow_ledger.py` 는 가짜 원장으로 기계를 고정한다. 그런데 이 파일이
막으려는 덫은 가짜로는 재현되지 않는다: `get_question` 이 돌려주는 것은
**세션에 매달린 ORM 행**이고, `LedgerEvidenceStore.commit` 이 그 객체의
`evidence_bytes` 를 직접 올린다. flush 를 막아도 그 세션의 다음 커밋이 실어
보낸다 -- SQLAlchemy 의 unit of work 가 그렇게 동작하기 때문이다.

그래서 **두 방향을 같이 건다.** 섀도를 쓰면 행이 그대로라는 것만 보면 그
테스트는 "원래 아무 일도 안 일어났다" 로도 통과한다. 섀도 없이 같은 코드를
돌려 행이 **실제로 바뀌는지**를 먼저 확인해야 앞의 초록이 의미를 갖는다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.evidence_store import LedgerEvidenceStore
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import ProposedBlob
from neos.workflow.deep_analysis.shadow import ShadowLedger

CHARGED = 4096


def _blob() -> ProposedBlob:
    return ProposedBlob(
        content_hash="c" * 16,
        source_url="https://example.com",
        http_status=200,
        raw_text="본문",
    )


async def _open(session) -> tuple[Ledger, str]:
    run_id = await create_run(session, "root?", "dev")
    ledger = Ledger(session, run_id)
    question_id = await ledger.open_question(
        "q?", None, value_est=1.0, cap_tokens=2000, depth=0
    )
    return ledger, question_id


async def _counts(session, run_id: str) -> tuple[int, int]:
    blobs = await session.scalar(
        text("SELECT COUNT(*) FROM deep_analysis_blobs WHERE run_id=:r"),
        {"r": run_id},
    )
    spent = await session.scalar(
        text("SELECT evidence_bytes FROM deep_analysis_questions WHERE run_id=:r"),
        {"r": run_id},
    )
    return int(blobs), int(spent)


@pytest.mark.asyncio
async def test_without_the_shadow_the_same_call_really_does_write():
    """앞 테스트의 초록이 의미를 갖게 하는 대조군이다.

    이것이 빨개지면 아래 테스트는 아무것도 증명하지 못한다 -- 막을 것이
    없는데 막았다고 말하는 것이 된다.
    """
    async with await db_manager.get_session() as session:
        ledger, question_id = await _open(session)
        store = LedgerEvidenceStore(ledger, question_id=question_id)

        await store.commit(_blob(), bytes_charged=CHARGED)

        assert await _counts(session, ledger.run_id) == (1, CHARGED)
        await session.rollback()


@pytest.mark.asyncio
async def test_the_shadow_leaves_the_blob_table_and_the_byte_count_alone():
    async with await db_manager.get_session() as session:
        ledger, question_id = await _open(session)
        shadow = ShadowLedger(ledger)
        store = LedgerEvidenceStore(shadow, question_id=question_id)

        await store.commit(_blob(), bytes_charged=CHARGED)
        await store.record_fetched("c" * 16, "/evidence/cccc.txt")
        # 섀도 안에서는 회계가 **진짜로** 돌아야 한다.
        assert await store.spent_bytes() == CHARGED

        # 세션을 실제로 내보내 본다. 섀도가 막는 것이 flush 호출 하나가
        # 아니라 **더럽혀진 객체 자체**라는 것이 여기서 갈린다.
        await session.flush()

        assert await _counts(session, ledger.run_id) == (0, 0)
        assert len(shadow.committed_blobs) == 1
        assert [kind for kind, _, _ in shadow.logged_events] == [
            "evidence_fetched_for_sandbox"
        ]
        await session.rollback()


@pytest.mark.asyncio
async def test_two_shadow_runs_do_not_see_each_other():
    """J3 가 반복 가능해야 하는 이유다.

    섀도가 쓰면 같은 run 을 두 번 돌릴 때 두 번째는 첫 번째가 남긴 blob 과
    바이트 위에서 돈다 -- 비교 결과가 실행 횟수에 의존하게 된다.
    """
    async with await db_manager.get_session() as session:
        ledger, question_id = await _open(session)

        spent = []
        for _ in range(2):
            store = LedgerEvidenceStore(
                ShadowLedger(ledger), question_id=question_id
            )
            await store.commit(_blob(), bytes_charged=CHARGED)
            spent.append(await store.spent_bytes())

        assert spent == [CHARGED, CHARGED]
        await session.rollback()
