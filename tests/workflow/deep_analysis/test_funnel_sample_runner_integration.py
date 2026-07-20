import json

import pytest

from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAEvent, DAQuestion, DARun
from neos.workflow.deep_analysis.funnel_sample import QuestionCase
from neos.workflow.deep_analysis.funnel_sample_runner import execute_case


CASE = QuestionCase("integration", "fact", "Integration question?")


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
        async with get_session_ctx() as session:
            run = await session.get(DARun, observation["run_id"])
            if run is not None:
                await session.delete(run)
                await session.commit()
