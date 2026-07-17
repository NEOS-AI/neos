import pytest

from neos.workflow.deep_analysis.models import (
    Effort,
    NodeSummary,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)


pytestmark = pytest.mark.no_db


def test_effort_values():
    assert Effort.SCOUT.value == "scout"
    assert {effort.value for effort in Effort} == {
        "scout",
        "dig",
        "split",
        "synth",
    }


def test_worker_result_defaults_include_blob_proposals():
    result = WorkerResult(question_id="q1", status="completed")

    assert result.claims == []
    assert result.blobs == []
    assert result.tokens_spent == 0
    assert result.dead_ends == []


def test_proposed_claim_and_blob_nesting():
    evidence = ProposedEvidence(
        source_url="https://example.com",
        excerpt="quoted source",
        raw_ref="0123456789abcdef",
    )
    claim = ProposedClaim(text="claim", confidence=0.6, evidence=[evidence])
    blob = ProposedBlob(
        content_hash="0123456789abcdef",
        source_url="https://example.com",
        http_status=200,
        raw_text="quoted source",
    )

    result = WorkerResult(
        question_id="q1",
        status="completed",
        claims=[claim],
        blobs=[blob],
    )

    assert result.claims[0].evidence[0].raw_ref == blob.content_hash


def test_verdict_and_node_summary_defaults():
    verdict = Verdict(ok=True)
    summary = NodeSummary(
        question_id="q1",
        answer="answer",
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )

    assert verdict.ok is True
    assert verdict.code == ""
    assert summary.conflicts == []
