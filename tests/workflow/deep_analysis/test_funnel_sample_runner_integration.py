import json

import pytest

from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAEvent, DAQuestion, DARun
from neos.workflow.deep_analysis.funnel_sample import QuestionCase
from neos.workflow.deep_analysis.funnel_sample_runner import execute_case


CASE = QuestionCase("integration", "fact", "Integration question?")


async def _delete_fixture_run(run_id: str) -> None:
    """이 테스트가 만든 run 을 지운다 -- 트리거를 잠깐 끄고.

    `deep_analysis_runs` -> `deep_analysis_events` 는 `ON DELETE CASCADE` 인데
    events 에는 UPDATE/DELETE 를 거부하는 append-only 트리거가 걸려 있다
    (마이그레이션 036). 둘이 겹치면 **이벤트가 하나라도 있는 run 은 지울 수
    없다.** 원장이 append-only 인 것은 의도이므로 트리거를 손대지 않는다.

    그런데 여기서는 지워야 한다. `deep_analysis_events` 는 로드맵 §5.2 의 수치가
    나오는 **증거 테이블**이고, 테스트가 만든 가짜 run 이 남으면 그 증거를
    오염시킨다. 그래서 삭제 순간에만 트리거를 끈다 -- 프로덕션은 못 지우고
    테스트는 자기가 만든 것만 치운다.

    이 테스트는 CI 가 마이그레이션을 적용한 적이 없어서(D66) 트리거 없는 DB 에서
    통과하고 있었다. 지금도 트리거의 유무는 DB 마다 다르다 -- 036 은 신선한 DB 에
    깔끔히 적용되지만, 이미 데이터가 있는 개발 DB 에는 FK 위반으로 적용되지
    않는다. 그래서 있으면 끄고 없으면 그냥 지운다.
    """
    from sqlalchemy import text

    trigger = "deep_analysis_events_append_only"

    async with get_session_ctx() as session:
        run = await session.get(DARun, run_id)
        if run is None:
            return

        found = await session.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = :name"), {"name": trigger}
        )
        guarded = found.scalar() is not None

        if guarded:
            await session.execute(
                text(f"ALTER TABLE deep_analysis_events DISABLE TRIGGER {trigger}")
            )
        try:
            await session.delete(run)
            await session.flush()
        finally:
            if guarded:
                await session.execute(
                    text(f"ALTER TABLE deep_analysis_events ENABLE TRIGGER {trigger}")
                )
        await session.commit()


@pytest.mark.asyncio
async def test_execute_case_creates_run_and_collects_scoped_signals():
    captured = {}

    async def stub_execute(
        session_factory,
        run_id,
        question,
        profile,
        *,
        timeout_seconds,
    ):
        captured.update(
            run_id=run_id,
            question=question,
            profile=profile,
            timeout_seconds=timeout_seconds,
        )
        async with session_factory() as session:
            session.add_all(
                [
                    DAEvent(
                        run_id=run_id,
                        kind="pass_completed",
                        qid=None,
                        payload=json.dumps(
                            {"new_claims": 1, "verified": 1}
                        ),
                    ),
                    DAEvent(
                        run_id=run_id,
                        kind="claim_graded",
                        qid=None,
                        payload=json.dumps(
                            {
                                "claim_id": "claim-1",
                                "outcome": "verified",
                                "code": "OK",
                                "deterministic": "passed",
                                "deterministic_code": "OK",
                                "agentic": "not_configured",
                                "evidence_count": 1,
                                "source_count": 1,
                                "fetched_source_count": 1,
                                "dead_source_count": 0,
                                "excerpt_chars": 80,
                                "quote_threshold": 0.8,
                                "best_quote_score": 1.0,
                            }
                        ),
                    ),
                    DAQuestion(
                        id="rootq001",
                        run_id=run_id,
                        parent_id=None,
                        text=question,
                        status="resolved",
                        depth=0,
                        value_est=1.0,
                        confidence=1.0,
                        spent_tokens=321,
                        cap_tokens=1000,
                        fail_streak=0,
                    ),
                ]
            )
            run = await session.get(DARun, run_id)
            run.status = "completed"
            await session.commit()
        return {"report_markdown": "TOP SECRET REPORT"}

    observation = await execute_case(
        CASE,
        "dev",
        session_factory=get_session_ctx,
        execute_fn=stub_execute,
        timeout_seconds=3900,
    )
    try:
        assert captured == {
            "run_id": observation["run_id"],
            "question": CASE.question,
            "profile": "dev",
            "timeout_seconds": 3900,
        }
        assert observation["status"] == "completed"
        assert observation["tokens_spent"] == 321
        assert observation["signals"]["claim_funnel"]["graded"] == 1
        assert "report_markdown" not in json.dumps(observation)
        assert "TOP SECRET REPORT" not in json.dumps(observation)
    finally:
        await _delete_fixture_run(observation["run_id"])
