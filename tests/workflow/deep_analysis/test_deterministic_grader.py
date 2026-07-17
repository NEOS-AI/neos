from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.graders.deterministic import (
    DeterministicGrader,
)
from neos.workflow.deep_analysis.models import ProposedClaim, ProposedEvidence


pytestmark = pytest.mark.no_db


@dataclass
class Blob:
    http_status: int
    raw_text: str


class FakeLedger:
    def __init__(self, blobs):
        self.blobs = blobs
        self.reads = []

    async def get_blob(self, content_hash):
        self.reads.append(content_hash)
        return self.blobs.get(content_hash)


def _claim(
    *,
    excerpt="real source text",
    confidence=0.6,
    raw_ref="blob1",
    url="https://example.com",
):
    return ProposedClaim(
        text="claim",
        confidence=confidence,
        evidence=[
            ProposedEvidence(
                source_url=url,
                excerpt=excerpt,
                raw_ref=raw_ref,
            )
        ],
    )


def _grader(ledger):
    return DeterministicGrader(
        ledger,
        quote_threshold=0.92,
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
    )


@pytest.mark.asyncio
async def test_no_evidence_fails_before_blob_read():
    ledger = FakeLedger({})

    verdict = await _grader(ledger).grade(
        ProposedClaim(text="claim", confidence=0.5)
    )

    assert not verdict.ok
    assert verdict.code == "E_NO_EVIDENCE"
    assert ledger.reads == []


@pytest.mark.asyncio
async def test_missing_or_dead_source_fails_from_blob_metadata():
    missing = await _grader(FakeLedger({})).grade(_claim())
    dead = await _grader(
        FakeLedger({"blob1": Blob(http_status=404, raw_text="")})
    ).grade(_claim())

    assert missing.code == "E_SOURCE_DEAD"
    assert dead.code == "E_SOURCE_DEAD"


@pytest.mark.asyncio
async def test_quote_mismatch_is_caught_with_salvage_url():
    ledger = FakeLedger(
        {"blob1": Blob(http_status=200, raw_text="the real content")}
    )

    verdict = await _grader(ledger).grade(
        _claim(excerpt="fabricated quote not present")
    )

    assert not verdict.ok
    assert verdict.code == "E_QUOTE_MISMATCH"
    assert verdict.salvage == "https://example.com"


@pytest.mark.asyncio
async def test_confidence_above_unique_source_cap_fails():
    ledger = FakeLedger(
        {"blob1": Blob(http_status=200, raw_text="real source text")}
    )

    verdict = await _grader(ledger).grade(_claim(confidence=0.9))

    assert not verdict.ok
    assert verdict.code == "E_CONFIDENCE_INFLATED"


@pytest.mark.asyncio
async def test_valid_claim_passes_without_network_io():
    ledger = FakeLedger(
        {"blob1": Blob(http_status=200, raw_text="real source text")}
    )

    verdict = await _grader(ledger).grade(_claim())

    assert verdict.ok
    assert verdict.code == ""
