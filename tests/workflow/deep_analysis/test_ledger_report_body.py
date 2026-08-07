"""리포트 본문은 job_completed 페이로드에 있다 -- report_path 컬럼이 아니라.

test_deep_analysis_analytics.py 와 같은 규율을 따른다: 실제 DB에 쓰고
각 테스트 끝에서 롤백한다. 남는 쓰기가 있으면 안 된다.
"""

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService
from neos.workflow.deep_analysis.ledger import Ledger, create_run


@pytest.mark.asyncio
async def test_report_markdown_reads_the_completed_job_payload():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log(
            "job_completed", None, {"report_markdown": "## 요약\n본문"}
        )

        assert await Ledger(s, run_id).report_markdown() == "## 요약\n본문"
        await s.rollback()


@pytest.mark.asyncio
async def test_report_markdown_is_none_before_the_run_completes():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log("job_started", None, {"profile": "dev"})

        assert await Ledger(s, run_id).report_markdown() is None
        await s.rollback()


@pytest.mark.asyncio
async def test_report_markdown_is_none_when_the_payload_has_no_body():
    """방어적으로 읽는다 -- 페이로드 모양이 바뀌어도 예외를 내지 않는다."""
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log("job_completed", None, {"run_id": run_id})

        assert await Ledger(s, run_id).report_markdown() is None
        await s.rollback()


@pytest.mark.asyncio
async def test_report_bodies_reads_many_runs_in_one_query():
    """G3는 수백 run을 훑는다 -- 단건 조회를 루프로 돌리면 run 수만큼 왕복한다."""
    async with await db_manager.get_session() as s:
        first = await create_run(s, "질문 A", "dev")
        second = await create_run(s, "질문 B", "dev")
        third = await create_run(s, "질문 C", "dev")
        await Ledger(s, first).log(
            "job_completed", None, {"report_markdown": "리포트 A"}
        )
        await Ledger(s, second).log(
            "job_completed", None, {"report_markdown": "리포트 B"}
        )
        # third 는 완료되지 않았다.
        await Ledger(s, third).log("job_started", None, {"profile": "dev"})

        bodies = await DeepAnalysisAnalyticsService(s).report_bodies(
            [first, second, third]
        )

        assert bodies == {first: "리포트 A", second: "리포트 B"}
        await s.rollback()


@pytest.mark.asyncio
async def test_report_bodies_returns_empty_for_no_run_ids():
    """빈 입력에서 질의를 아예 내지 않는다 -- IN () 은 DB마다 다르게 군다."""
    async with await db_manager.get_session() as s:
        assert await DeepAnalysisAnalyticsService(s).report_bodies([]) == {}
        await s.rollback()
