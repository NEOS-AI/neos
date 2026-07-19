"""M4 Task 5 (review fix): conflict reinvestigation against the REAL ledger.

The unit tests in ``test_orchestrator_m4.py`` drive ``_finalize`` with a fake
ledger. This module exercises the actual state-machine contract that the
review flagged: a high-value equal-tier conflict whose owning question is
already ``resolved`` (terminal) must be REOPENED via the §6.7-sanctioned
``reopen_for_reinvestigation`` path and then re-investigated -- and the global
cap must be durable across a resumed ``_finalize`` because it is gated on the
event log, not an in-memory counter.
"""

import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register all FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    ConflictNote,
    NodeSummary,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator


def _two_claim_result(question_id: str) -> WorkerResult:
    """A completed pass with two tier-2 (example.com) claims -> equal-tier
    conflict fodder, high self-assessment so the question resolves."""
    return WorkerResult(
        question_id=question_id,
        status="completed",
        blobs=[
            ProposedBlob(
                content_hash="a" * 16,
                source_url="https://example.com/a",
                http_status=200,
                raw_text="claim A evidence",
            ),
            ProposedBlob(
                content_hash="b" * 16,
                source_url="https://example.net/b",
                http_status=200,
                raw_text="claim B evidence",
            ),
        ],
        claims=[
            ProposedClaim(
                text="Latency dropped by 40%",
                confidence=0.6,
                evidence=[
                    ProposedEvidence(
                        "https://example.com/a", "dropped 40%", "a" * 16
                    )
                ],
            ),
            ProposedClaim(
                text="Latency rose by 10%",
                confidence=0.6,
                evidence=[
                    ProposedEvidence(
                        "https://example.net/b", "rose 10%", "b" * 16
                    )
                ],
            ),
        ],
        tokens_spent=100,
        self_assessment=0.9,
    )


class _ReinvestWorker:
    """Fake worker for the reinvestigation round: produces one fresh claim and
    burns tokens so the reopened question demonstrably gets re-investigated."""

    async def investigate(self, brief, effort, question_id, repairs=None, question_text=""):
        return WorkerResult(
            question_id=question_id,
            status="completed",
            claims=[
                ProposedClaim(
                    text="Reinvestigated finding",
                    confidence=0.7,
                    evidence=[
                        ProposedEvidence(
                            "https://example.org/c", "fresh", "c" * 16
                        )
                    ],
                )
            ],
            blobs=[
                ProposedBlob(
                    content_hash="c" * 16,
                    source_url="https://example.org/c",
                    http_status=200,
                    raw_text="fresh evidence",
                )
            ],
            tokens_spent=50,
            self_assessment=0.8,
        )

    def flush_partial(self, question_id):
        return WorkerResult(question_id=question_id, status="partial")


class _OkGrader:
    async def grade(self, claim, *args):
        return Verdict(ok=True)


class _ReportOkGrader:
    async def grade(self, report, root_id):
        return Verdict(ok=True)


class _ConflictSynth:
    """reduce_tree returns a single root summary carrying a persistent
    equal-tier conflict between the two child claims; assemble is a stub."""

    def __init__(self, root_id, conflict):
        self.root_id = root_id
        self.conflict = conflict
        self.assemble_calls = 0

    async def reduce_tree(self, root_id):
        return {
            self.root_id: NodeSummary(
                self.root_id, "루트", [], 0.9, [], conflicts=[self.conflict]
            )
        }

    async def assemble(self, root_summary, child_summaries, caveats):
        self.assemble_calls += 1
        return "DRAFT\n\n## 출처"


class _CleanRenderer:
    async def render(self, draft):
        return draft + "\n[1] http://x"


async def _event_count(session, run_id, kind):
    return int(
        await session.scalar(
            text(
                "SELECT COUNT(*) FROM deep_analysis_events "
                "WHERE run_id=:r AND kind=:k"
            ),
            {"r": run_id, "k": kind},
        )
        or 0
    )


@pytest.mark.asyncio
async def test_reinvestigation_reopens_resolved_question_and_is_durable():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        root_id = await ledger.open_question(
            "root?", None, value_est=1.0, cap_tokens=100000, depth=0
        )
        child_id = await ledger.open_question(
            "child?", root_id, value_est=0.9, cap_tokens=50000, depth=1
        )

        # Resolve the child with two verified, equal-tier (tier-2) claims.
        await ledger._transition(child_id, "investigating")
        result = _two_claim_result(child_id)
        await ledger.commit_pass(
            child_id,
            result,
            {c.text: Verdict(ok=True) for c in result.claims},
        )
        child = await ledger.get_question(child_id)
        assert child.status == "resolved"

        # The two claim ids belong to the child -> conflict maps to child.
        claim_ids = list(
            (
                await session.execute(
                    text(
                        "SELECT id FROM deep_analysis_claims "
                        "WHERE run_id=:r AND question_id=:q ORDER BY id"
                    ),
                    {"r": run_id, "q": child_id},
                )
            ).scalars()
        )
        assert len(claim_ids) == 2
        conflict = ConflictNote(claim_ids[0], claim_ids[1], "상반")

        synth = _ConflictSynth(root_id, conflict)
        orch = Orchestrator(
            session,
            run_id,
            worker_factory=_ReinvestWorker,
            grader=_OkGrader(),
            ledger=ledger,
            synthesizer=synth,
            citation_renderer=_CleanRenderer(),
            report_grader=_ReportOkGrader(),
        )

        spent_before = child.spent_tokens
        report = await orch._finalize(root_id)

        # (a) the resolved child was reopened then re-investigated.
        assert await _event_count(session, run_id, "question_reopened") == 1
        child_after = await ledger.get_question(child_id)
        assert child_after.spent_tokens > spent_before  # a real round ran
        # (b) a conflict_reinvestigation event exists.
        assert await _event_count(session, run_id, "conflict_reinvestigation") == 1
        # (c) reinvestigation fired at most once within the run.
        assert orch._reinvestigation_count == 1
        assert "DRAFT" in report

        # (d) resumed _finalize with a prior event does NOT reinvestigate again.
        orch._reinvestigation_count = 0  # simulate crash-recovery reset
        synth.assemble_calls = 0
        spent_mid = (await ledger.get_question(child_id)).spent_tokens
        await orch._finalize(root_id)
        assert await _event_count(session, run_id, "conflict_reinvestigation") == 1
        assert await _event_count(session, run_id, "question_reopened") == 1
        assert orch._reinvestigation_count == 0  # never fired
        assert (await ledger.get_question(child_id)).spent_tokens == spent_mid

        await session.rollback()
