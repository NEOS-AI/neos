"""매니페스트 판독 -- 재개하면 둘이 되고, 마지막 것이 유효 구성이다."""

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.manifest import MANIFEST_KIND
from neos.workflow.deep_analysis.manifest_reader import (
    manifests_for,
    runs_without_manifest,
)


@pytest.mark.asyncio
async def test_manifests_for_returns_the_payload():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log(
            MANIFEST_KIND, None, {"manifest_version": 1, "profile": "dev"}
        )

        found = await manifests_for(s, [run_id])

        assert found[run_id]["profile"] == "dev"
        await s.rollback()


@pytest.mark.asyncio
async def test_resume_keeps_both_manifests_and_the_reader_takes_the_last():
    """append-only (D8). 재개는 두 번째 매니페스트를 append 한다.

    지우지도 UPDATE 하지도 않는다. 크래시와 재개 사이에 설정이 바뀌면
    원장이 그것을 말한다 -- 지금은 어디에도 안 남는다.
    """
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        ledger = Ledger(s, run_id)
        await ledger.log(
            MANIFEST_KIND, None, {"manifest_version": 1, "profile": "dev"}
        )
        await ledger.log(
            MANIFEST_KIND, None, {"manifest_version": 1, "profile": "default"}
        )

        found = await manifests_for(s, [run_id])

        assert found[run_id]["profile"] == "default"
        await s.rollback()


@pytest.mark.asyncio
async def test_runs_without_manifest_names_the_gap():
    async with await db_manager.get_session() as s:
        with_manifest = await create_run(s, "질문 A", "dev")
        await Ledger(s, with_manifest).log(
            MANIFEST_KIND, None, {"manifest_version": 1}
        )
        without = await create_run(s, "질문 B", "dev")

        missing = await runs_without_manifest(s, [with_manifest, without])

        assert missing == [without]
        await s.rollback()


@pytest.mark.asyncio
async def test_empty_run_list_is_not_a_gap():
    async with await db_manager.get_session() as s:
        assert await runs_without_manifest(s, []) == []
        await s.rollback()
