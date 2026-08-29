"""이벤트가 있는 run 을 지울 수 있는가 -- 그리고 실수로는 지울 수 없는가 (SCHEMA2).

036 이 두 가지를 동시에 걸어 놓았다: `deep_analysis_events.run_id` 가
`ON DELETE CASCADE` 이고, 같은 테이블에 UPDATE/DELETE 를 무조건 거부하는
트리거가 있다. 겹치면 **이벤트가 하나라도 있는 run 은 삭제할 수 없다** --
테스트뿐 아니라 프로덕션도 그렇다. 대화 삭제나 보존기한 요구가 생기면 여기서
걸린다.

append-only(D8)를 없애서 푸는 것이 아니라, **의도적인 purge 트랜잭션만**
통과시켜서 푼다. 기본은 여전히 거부다 -- `deep_analysis_events` 는 §10.1 이
"지우면 재현 불가" 로 못박은 증거 테이블이고, 그 성질은 그대로 둔다.
"""

import pytest
from sqlalchemy import text

from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run, purge_run


async def _seed_run_with_events(session) -> str:
    """run 하나와 이벤트 두 건을 심고 run_id 를 돌려준다.

    INSERT 를 손으로 쓰지 않고 `create_run` 을 쓰는 이유: 컬럼 목록을 손으로
    나열하면 `deep_analysis_runs` 에 NOT NULL 컬럼이 하나 늘어나는 순간 낡는다.
    실제로 이 파일을 쓰면서 `profile` 과 `created_at` 에 연달아 걸렸다.
    """
    run_id = await create_run(session, "purge 테스트용 루트 질문", "dev")
    ledger = Ledger(session, run_id)
    await ledger.log("token_budget_reserved", None, {"stage": "probe"})
    await ledger.log("synth_pass", None, {"stage": "probe"})
    await session.commit()
    return run_id


@pytest.mark.asyncio
async def test_events_still_reject_a_plain_delete():
    """일상 경로에서는 아무것도 바뀌지 않는다.

    이 테스트가 없으면 purge 경로를 여는 변경이 append-only 를 통째로
    없애 버려도 아무도 모른다 -- D8 이 지키려는 것이 정확히 이것이다.
    """
    async with await db_manager.get_session() as s:
        run_id = await _seed_run_with_events(s)

        with pytest.raises(Exception, match="append-only"):
            await s.execute(
                text("DELETE FROM deep_analysis_events WHERE run_id = :r"),
                {"r": run_id},
            )
        await s.rollback()


@pytest.mark.asyncio
async def test_events_still_reject_a_plain_update():
    """UPDATE 도 마찬가지다. 트리거는 `BEFORE UPDATE OR DELETE` 이고
    purge 플래그는 **삭제만** 여는 것이 아니라 그 트리거 전체를 여므로,
    UPDATE 쪽도 기본 거부인지 함께 고정한다."""
    async with await db_manager.get_session() as s:
        run_id = await _seed_run_with_events(s)

        with pytest.raises(Exception, match="append-only"):
            await s.execute(
                text(
                    "UPDATE deep_analysis_events SET kind = 'tampered' "
                    "WHERE run_id = :r"
                ),
                {"r": run_id},
            )
        await s.rollback()


@pytest.mark.asyncio
async def test_a_run_with_events_cannot_be_deleted_by_accident():
    """SCHEMA2 가 서술한 그 상태 -- CASCADE 가 트리거에 막힌다.

    purge 경로를 거치지 않는 `DELETE FROM deep_analysis_runs` 는 여전히
    실패해야 한다. 이것이 통과하면 CASCADE 가 증거 테이블을 조용히 비운다.
    """
    async with await db_manager.get_session() as s:
        run_id = await _seed_run_with_events(s)

        with pytest.raises(Exception, match="append-only"):
            await s.execute(
                text("DELETE FROM deep_analysis_runs WHERE id = :r"),
                {"r": run_id},
            )
        await s.rollback()


@pytest.mark.asyncio
async def test_purge_run_removes_the_run_and_its_events():
    """의도적인 purge 는 통과한다 -- SCHEMA2 가 열어야 했던 그 경로다."""
    async with await db_manager.get_session() as s:
        run_id = await _seed_run_with_events(s)

        deleted = await purge_run(s, run_id)
        await s.commit()

        assert deleted == 1
        remaining_runs = await s.scalar(
            text("SELECT count(*) FROM deep_analysis_runs WHERE id = :r"),
            {"r": run_id},
        )
        remaining_events = await s.scalar(
            text("SELECT count(*) FROM deep_analysis_events WHERE run_id = :r"),
            {"r": run_id},
        )
        assert remaining_runs == 0
        assert remaining_events == 0


@pytest.mark.asyncio
async def test_the_purge_flag_does_not_outlive_its_transaction():
    """`SET LOCAL` 이므로 플래그는 트랜잭션과 함께 끝난다.

    이것이 이 설계의 안전장치 전부다. 플래그가 세션에 남으면 그 커넥션이
    풀로 돌아간 뒤 **다음 요청이 append-only 없이 돈다** -- 커넥션 풀에서는
    조용하고 재현이 어려운 종류의 사고다.
    """
    async with await db_manager.get_session() as s:
        first_run = await _seed_run_with_events(s)
        await purge_run(s, first_run)
        await s.commit()

        # 같은 세션, 새 트랜잭션. 플래그가 살아 있다면 아래가 통과해 버린다.
        second_run = await _seed_run_with_events(s)
        with pytest.raises(Exception, match="append-only"):
            await s.execute(
                text("DELETE FROM deep_analysis_events WHERE run_id = :r"),
                {"r": second_run},
            )
        await s.rollback()


@pytest.mark.asyncio
async def test_purging_an_unknown_run_reports_zero_rather_than_raising():
    """없는 run 을 지우는 것은 오류가 아니라 0 건이다 -- 보존기한 배치가
    같은 run 을 두 번 집어도 두 번째가 터지지 않아야 한다."""
    async with await db_manager.get_session() as s:
        deleted = await purge_run(s, "ffffffff")
        await s.commit()

        assert deleted == 0
