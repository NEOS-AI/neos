import re

import pytest
from sqlalchemy import text

import neos.database.models  # noqa: F401 - register Base metadata
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.citation import CitationRenderer
from neos.workflow.deep_analysis.graders.deterministic import (
    DeterministicGrader,
)
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.llm import LLMResponse
from neos.workflow.deep_analysis.models import (
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.synthesizer import Synthesizer


class FakeWorker:
    async def investigate(self, brief, effort, question_id, repairs=None):
        blob = ProposedBlob(
            content_hash="abcdef0123456789",
            source_url="https://example.com/source",
            http_status=200,
            raw_text="Fact body text from the source.",
        )
        return WorkerResult(
            question_id=question_id,
            status="completed",
            blobs=[blob],
            claims=[
                ProposedClaim(
                    text="A verified fact",
                    confidence=0.6,
                    evidence=[
                        ProposedEvidence(
                            source_url=blob.source_url,
                            excerpt="Fact body text from the source.",
                            raw_ref=blob.content_hash,
                        )
                    ],
                )
            ],
            tokens_spent=100,
            self_assessment=0.8,
        )


class FakeComposer:
    async def __call__(self, model, prompt, **kwargs):
        marker = re.search(r"\[C:([0-9a-f]{8})\]", prompt).group(0)
        return LLMResponse(
            text=(
                f"## 요약\nA verified fact {marker}\n\n"
                f"## 본문\nA verified fact {marker}\n\n"
                "## 한계와 미확인 사항\n없음\n\n## 출처"
            ),
            input_tokens=10,
            output_tokens=10,
            model=model,
        )


@pytest.mark.asyncio
async def test_orchestrator_commits_verified_claims_and_resolves_citations():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "Root question?", "dev")
        ledger = Ledger(session, run_id)
        grader = DeterministicGrader(
            ledger,
            quote_threshold=0.92,
            confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
        )
        events = []

        async def decompose(_root):
            return [{"text": "Sub question", "value_est": 0.8}]

        orchestrator = Orchestrator(
            session,
            run_id,
            worker_factory=FakeWorker,
            grader=grader,
            decompose_fn=decompose,
            synthesizer=Synthesizer(ledger, llm_call=FakeComposer()),
            citation_renderer=CitationRenderer(ledger),
            event_sink=lambda kind, payload: events.append((kind, payload)),
            global_token_cap=1000,
        )

        result = await orchestrator.run("Root question?")

        verified_count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM deep_analysis_claims "
                "WHERE run_id=:run_id AND status='verified'"
            ),
            {"run_id": run_id},
        )
        statuses = dict(
            (
                await session.execute(
                    text(
                        "SELECT text, status FROM deep_analysis_questions "
                        "WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).all()
        )

        assert verified_count == 1
        assert statuses["Root question?"] == "split"
        assert statuses["Sub question"] == "resolved"
        assert "[C:" not in result["report_markdown"]
        assert "https://example.com/source" in result["report_markdown"]
        assert events[-1][0] == "completed"
        await session.rollback()
