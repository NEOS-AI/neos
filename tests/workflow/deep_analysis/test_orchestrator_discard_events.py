"""Task 3: the orchestrator logs a `claim_discarded` ledger event for every
claim entailment dropped before grading, so a later offline pass can re-grade
what would otherwise be invisible recall loss. NO real LLM/network call
happens anywhere in this module -- the synthesizer/citation seams are faked
exactly like the neighboring M4 integration test.
"""

import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import neos.database.models  # noqa: F401 - register Base metadata / FK targets
from neos.database.connection import db_manager
from neos.database.deep_analysis_models import DAEvent
from neos.workflow.deep_analysis.citation import CitationRenderer
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.llm import LLMResponse
from neos.workflow.deep_analysis.models import (
    ENTAILMENT_TRUNCATED,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.synthesizer import Synthesizer


# --- stubs adapted from test_orchestrator_m4_integration.py (self-contained
# copies, no cross-module import -- see task-3 ruling on test duplication) --


class OkDet:
    async def grade(self, claim):
        return Verdict(ok=True)


class OkReportGrader:
    async def grade(self, report, root_id):
        return Verdict(ok=True)


async def _no_split(_text, *_a):
    return []


def _no_decompose(_root):
    """No initial split: keeps the root question itself open so the worker
    investigates it directly and `question.value_est` in the discard-event
    payload is the root's 1.0 -- matching what Task 4 expects to read back.
    """
    return []


class PlainJSON:
    """reduce_node seam: conflict-free NodeSummary keyed by node id."""

    async def __call__(self, model, prompt, **kw):
        qid = re.search(r"질문 ID: (\w+)", prompt).group(1)
        return {
            "question_id": qid,
            "answer": "노드 요약",
            "key_claim_ids": [],
            "confidence": 0.7,
            "caveats": [],
            "conflicts": [],
        }, SimpleNamespace(input_tokens=len(prompt) // 4, output_tokens=10)


class PlainAssembleLLM:
    """assemble seam: a fixed report with no [C:...] markers, so the real
    CitationRenderer has nothing to resolve and cannot raise orphan errors."""

    async def __call__(self, model, prompt, **kw):
        text = "## 요약\n연구 종합.\n\n## 본문\n본문 내용.\n\n## 출처"
        return LLMResponse(text=text, input_tokens=5, output_tokens=5, model=model)


# --- fake worker for this task's scenario ---------------------------------


def _evidence():
    return [
        ProposedEvidence(
            "https://example.com/source",
            "Direct evidence.",
            "a" * 16,
        )
    ]


class DiscardWorker:
    """One completed pass: one surviving claim, two discarded."""

    def __init__(self, discarded=2, entailment_skipped=None):
        self.discarded = discarded
        self.entailment_skipped = entailment_skipped

    async def investigate(
        self, brief, effort, qid, repairs=None, question_text=""
    ):
        return WorkerResult(
            question_id=qid,
            status="completed",
            blobs=[
                ProposedBlob(
                    "a" * 16, "https://example.com/source", 200, "A body"
                )
            ],
            claims=[ProposedClaim("kept claim", 0.6, _evidence())],
            discarded_claims=[
                ProposedClaim(f"discarded {index}", 0.6, _evidence())
                for index in range(self.discarded)
            ],
            tokens_spent=100,
            self_assessment=0.9,
            entailment_skipped=self.entailment_skipped,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


async def _discard_events(session, run_id):
    rows = await session.execute(
        select(DAEvent.qid, DAEvent.payload).where(
            DAEvent.run_id == run_id,
            DAEvent.kind == "claim_discarded",
        )
    )
    return rows.all()


def _make_orchestrator(session, run_id, ledger, worker_factory):
    synth = Synthesizer(ledger, llm_call=PlainAssembleLLM(), json_call=PlainJSON())
    orch = Orchestrator(
        session,
        run_id,
        worker_factory,
        OkDet(),
        ledger=ledger,
        synthesizer=synth,
        citation_renderer=CitationRenderer(ledger),
        report_grader=OkReportGrader(),
        decompose_fn=_no_decompose,
        global_token_cap=5000,
    )
    orch._split_decompose = _no_split
    return orch


@pytest.mark.asyncio
async def test_orchestrator_logs_one_event_per_discarded_claim():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = _make_orchestrator(
            session, run_id, ledger, lambda: DiscardWorker(discarded=2)
        )
        await orch.run("root?")

        events = await _discard_events(session, run_id)

    assert len(events) == 2
    payloads = sorted(
        (json.loads(payload) for _, payload in events),
        key=lambda item: item["text"],
    )
    assert [item["text"] for item in payloads] == [
        "discarded 0",
        "discarded 1",
    ]
    assert payloads[0]["confidence"] == 0.6
    assert payloads[0]["value_est"] == 1.0
    assert payloads[0]["evidence"] == [
        {
            "source_url": "https://example.com/source",
            "excerpt": "Direct evidence.",
            "raw_ref": "a" * 16,
        }
    ]
    assert all(qid for qid, _ in events)


@pytest.mark.asyncio
async def test_orchestrator_logs_no_event_when_nothing_discarded():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = _make_orchestrator(
            session, run_id, ledger, lambda: DiscardWorker(discarded=0)
        )
        await orch.run("root?")

        events = await _discard_events(session, run_id)

    assert events == []


async def _skip_events(session, run_id):
    rows = await session.execute(
        select(DAEvent.qid, DAEvent.payload).where(
            DAEvent.run_id == run_id,
            DAEvent.kind == "entailment_filter_skipped",
        )
    )
    return rows.all()


@pytest.mark.asyncio
async def test_orchestrator_logs_one_event_when_entailment_was_skipped():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = _make_orchestrator(
            session,
            run_id,
            ledger,
            lambda: DiscardWorker(discarded=0, entailment_skipped=ENTAILMENT_TRUNCATED),
        )
        await orch.run("root?")

        events = await _skip_events(session, run_id)

    assert len(events) == 1
    qid, payload = events[0]
    assert qid
    # C4: 예전에는 다섯 원인이 전부 상수 "entailment_unavailable" 로 적혔다.
    # 이제 워커가 아는 실제 사유가 그대로 원장에 남는다.
    assert json.loads(payload) == {
        "claim_count": 1,
        "reason": ENTAILMENT_TRUNCATED,
    }


@pytest.mark.asyncio
async def test_orchestrator_logs_no_skip_event_on_a_normal_pass():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        orch = _make_orchestrator(
            session,
            run_id,
            ledger,
            lambda: DiscardWorker(discarded=2, entailment_skipped=None),
        )
        await orch.run("root?")

        events = await _skip_events(session, run_id)

    assert events == []
