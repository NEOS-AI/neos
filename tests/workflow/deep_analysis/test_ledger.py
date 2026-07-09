import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register all FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import (
    IllegalTransition,
    Ledger,
    create_run,
)
from neos.workflow.deep_analysis.models import (
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)


def _result(
    question_id: str,
    *,
    text_value: str = "MoE routing lowers cost",
    confidence: float = 0.6,
    self_assessment: float = 0.8,
) -> WorkerResult:
    content_hash = "0123456789abcdef"
    source_url = "https://example.com/source"
    raw_text = "Evidence says MoE routing lowers cost."
    return WorkerResult(
        question_id=question_id,
        status="completed",
        blobs=[
            ProposedBlob(
                content_hash=content_hash,
                source_url=source_url,
                http_status=200,
                raw_text=raw_text,
            )
        ],
        claims=[
            ProposedClaim(
                text=text_value,
                confidence=confidence,
                evidence=[
                    ProposedEvidence(
                        source_url=source_url,
                        excerpt="MoE routing lowers cost",
                        raw_ref=content_hash,
                    )
                ],
            )
        ],
        tokens_spent=100,
        self_assessment=self_assessment,
    )


@pytest.mark.asyncio
async def test_ac_a_legal_and_illegal_question_transitions():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        question_id = await ledger.open_question(
            "q?",
            None,
            value_est=1.0,
            cap_tokens=2000,
            depth=0,
        )

        await ledger._transition(question_id, "investigating")
        await ledger._transition(question_id, "resolved")

        with pytest.raises(IllegalTransition):
            await ledger._transition(question_id, "open")

        await session.rollback()


@pytest.mark.asyncio
async def test_ac_b_same_hash_merges_evidence_and_bumps_confidence():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        question_id = await ledger.open_question(
            "q?",
            None,
            value_est=1.0,
            cap_tokens=2000,
            depth=0,
        )

        await ledger._transition(question_id, "investigating")
        first = _result(question_id, self_assessment=0.2)
        await ledger.commit_pass(
            question_id,
            first,
            {first.claims[0].text: Verdict(ok=True)},
        )
        await ledger._transition(question_id, "investigating")
        second = _result(question_id, self_assessment=0.8)
        await ledger.commit_pass(
            question_id,
            second,
            {second.claims[0].text: Verdict(ok=True)},
        )

        row = await session.execute(
            text(
                "SELECT COUNT(*), MAX(confidence) "
                "FROM deep_analysis_claims WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        )
        count, confidence = row.one()
        evidence_count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM deep_analysis_evidence "
                "WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        )

        assert count == 1
        assert confidence == pytest.approx(0.75)
        assert evidence_count == 2
        await session.rollback()


@pytest.mark.asyncio
async def test_ac_c_recover_uses_state_machine_to_reopen_investigating():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        question_id = await ledger.open_question(
            "q?",
            None,
            value_est=1.0,
            cap_tokens=2000,
            depth=0,
        )
        await ledger._transition(question_id, "investigating")

        recovered = await ledger.recover()
        question = await ledger.get_question(question_id)

        assert recovered == 1
        assert question.status == "open"
        await session.rollback()


@pytest.mark.asyncio
async def test_ac_d_identical_claims_do_not_merge_across_runs():
    async with await db_manager.get_session() as session:
        run_ids = [
            await create_run(session, "A?", "dev"),
            await create_run(session, "B?", "dev"),
        ]

        for run_id in run_ids:
            ledger = Ledger(session, run_id)
            question_id = await ledger.open_question(
                "q?",
                None,
                value_est=1.0,
                cap_tokens=2000,
                depth=0,
            )
            await ledger._transition(question_id, "investigating")
            result = _result(question_id, text_value="identical fact")
            await ledger.commit_pass(question_id, result, {})

        for run_id in run_ids:
            row = await session.execute(
                text(
                    "SELECT COUNT(*), MAX(confidence) "
                    "FROM deep_analysis_claims WHERE run_id=:run_id"
                ),
                {"run_id": run_id},
            )
            count, confidence = row.one()
            assert count == 1
            assert confidence == pytest.approx(0.6)

        await session.rollback()


@pytest.mark.asyncio
async def test_commit_pass_stores_blob_before_evidence_and_records_events():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        question_id = await ledger.open_question(
            "q?",
            None,
            value_est=1.0,
            cap_tokens=2000,
            depth=0,
        )
        await ledger._transition(question_id, "investigating")
        result = _result(question_id)

        await ledger.commit_pass(
            question_id,
            result,
            {result.claims[0].text: Verdict(ok=True)},
        )

        blob_count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM deep_analysis_blobs "
                "WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        )
        event_kinds = (
            await session.execute(
                text(
                    "SELECT kind FROM deep_analysis_events "
                    "WHERE run_id=:run_id ORDER BY seq"
                ),
                {"run_id": run_id},
            )
        ).scalars().all()

        assert blob_count == 1
        assert "claim_verified" in event_kinds
        assert event_kinds[-1] == "pass_completed"
        await session.rollback()
