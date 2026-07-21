import json

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
        result.confidence_clamped_count = 999
        result.confidence_clamped_by_source_count = {
            "0": 1,
            "1": 2,
            "2": True,
            "3_plus": 3,
            "unknown": 99,
        }

        await ledger.commit_pass(
            question_id,
            result,
            {
                result.claims[0].text: Verdict(
                    ok=True,
                    diagnostics={
                        "deterministic": "passed",
                        "deterministic_code": "",
                        "agentic": "attempted_passed",
                        "agentic_label": "SUPPORTS",
                        "evidence_count": 1,
                        "source_count": 1,
                        "fetched_source_count": 1,
                        "dead_source_count": 0,
                        "excerpt_chars": 23,
                        "best_quote_score": 1.0,
                        "quote_threshold": 0.92,
                        "raw_text": "must not be persisted",
                        "source_url": "https://secret.example",
                    },
                )
            },
        )

        blob_count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM deep_analysis_blobs "
                "WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        )
        stored_blob = await ledger.get_blob(result.blobs[0].content_hash)
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
        assert stored_blob.raw_text == result.blobs[0].raw_text
        assert event_kinds[-3:] == [
            "claim_graded",
            "claim_verified",
            "pass_completed",
        ]

        graded_payload = await session.scalar(
            text(
                "SELECT payload FROM deep_analysis_events "
                "WHERE run_id=:run_id AND kind='claim_graded'"
            ),
            {"run_id": run_id},
        )
        graded_payload = json.loads(graded_payload)
        assert graded_payload["outcome"] == "verified"
        assert graded_payload["deterministic"] == "passed"
        assert graded_payload["agentic"] == "attempted_passed"
        assert graded_payload["best_quote_score"] == 1.0
        assert "raw_text" not in graded_payload
        assert "source_url" not in graded_payload
        pass_payload = await session.scalar(
            text(
                "SELECT payload FROM deep_analysis_events "
                "WHERE run_id=:run_id AND kind='pass_completed'"
            ),
            {"run_id": run_id},
        )
        pass_payload = json.loads(pass_payload)
        assert pass_payload["confidence_clamped_by_source_count"] == {
            "0": 1,
            "1": 2,
            "2": 0,
            "3_plus": 3,
        }
        assert pass_payload["confidence_clamped_count"] == 6
        assert "unknown" not in pass_payload["confidence_clamped_by_source_count"]
        assert "requested_confidence" not in json.dumps(pass_payload)
        assert event_kinds[-1] == "pass_completed"
        await session.rollback()


@pytest.mark.asyncio
async def test_token_budget_state_replays_only_valid_run_scoped_events():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        other_run_id = await create_run(session, "other?", "dev")
        ledger = Ledger(session, run_id)
        other = Ledger(session, other_run_id)

        await ledger.log(
            "token_budget_reserved",
            None,
            {"reservation_id": "settled", "reserved_tokens": 40},
        )
        await ledger.log(
            "token_budget_settled",
            None,
            {"reservation_id": "settled", "actual_tokens": 25},
        )
        # A second terminal event must not alter the first valid outcome.
        await ledger.log(
            "token_budget_released",
            None,
            {"reservation_id": "settled"},
        )
        await ledger.log(
            "token_budget_reserved",
            None,
            {"reservation_id": "released", "reserved_tokens": 30},
        )
        await ledger.log(
            "token_budget_released",
            None,
            {"reservation_id": "released"},
        )
        await ledger.log(
            "token_budget_reserved",
            None,
            {"reservation_id": "orphan", "reserved_tokens": 20},
        )
        await ledger.log(
            "token_budget_reserved",
            None,
            {"reservation_id": "duplicate", "reserved_tokens": 10},
        )
        await ledger.log(
            "token_budget_reserved",
            None,
            {"reservation_id": "duplicate", "reserved_tokens": 999},
        )
        await ledger.log(
            "token_budget_settled",
            None,
            {"reservation_id": "duplicate", "actual_tokens": 7},
        )
        await ledger.log(
            "token_budget_settled",
            None,
            {"reservation_id": "duplicate", "actual_tokens": 2},
        )
        await ledger.log("token_budget_reserved", None, {"reserved_tokens": 50})
        await ledger.log(
            "token_budget_settled",
            None,
            {"reservation_id": "unknown", "actual_tokens": 5},
        )
        await other.log(
            "token_budget_reserved",
            None,
            {"reservation_id": "foreign", "reserved_tokens": 99},
        )

        consumed, outstanding = await ledger.token_budget_state()

        assert consumed == 32
        assert outstanding == {"orphan": 20}
        await session.rollback()
