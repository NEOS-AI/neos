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

    verdict = await _grader(ledger).grade(ProposedClaim(text="claim", confidence=0.5))

    assert not verdict.ok
    assert verdict.code == "E_NO_EVIDENCE"
    assert verdict.diagnostics == {
        "deterministic": "rejected",
        "deterministic_code": "E_NO_EVIDENCE",
        "evidence_count": 0,
        "source_count": 0,
        "fetched_source_count": 0,
        "dead_source_count": 0,
        "excerpt_chars": 0,
        "best_quote_score": None,
        "quote_threshold": 0.92,
    }
    assert ledger.reads == []


@pytest.mark.asyncio
async def test_missing_or_dead_source_fails_from_blob_metadata():
    missing = await _grader(FakeLedger({})).grade(_claim())
    dead = await _grader(
        FakeLedger({"blob1": Blob(http_status=404, raw_text="")})
    ).grade(_claim())

    assert missing.code == "E_SOURCE_DEAD"
    assert dead.code == "E_SOURCE_DEAD"
    assert missing.diagnostics["fetched_source_count"] == 0
    assert missing.diagnostics["dead_source_count"] == 1
    assert missing.diagnostics["best_quote_score"] is None


@pytest.mark.asyncio
async def test_quote_mismatch_is_caught_with_salvage_url():
    ledger = FakeLedger({"blob1": Blob(http_status=200, raw_text="the real content")})

    verdict = await _grader(ledger).grade(
        _claim(excerpt="fabricated quote not present")
    )

    assert not verdict.ok
    assert verdict.code == "E_QUOTE_MISMATCH"
    assert verdict.salvage == "https://example.com"
    assert verdict.diagnostics["deterministic"] == "rejected"
    assert verdict.diagnostics["deterministic_code"] == "E_QUOTE_MISMATCH"
    assert verdict.diagnostics["fetched_source_count"] == 1
    assert verdict.diagnostics["dead_source_count"] == 0
    assert 0.0 <= verdict.diagnostics["best_quote_score"] < 0.92


@pytest.mark.asyncio
async def test_confidence_above_unique_source_cap_fails():
    ledger = FakeLedger({"blob1": Blob(http_status=200, raw_text="real source text")})

    verdict = await _grader(ledger).grade(_claim(confidence=0.9))

    assert not verdict.ok
    assert verdict.code == "E_CONFIDENCE_INFLATED"
    assert verdict.diagnostics["best_quote_score"] == 1.0


@pytest.mark.asyncio
async def test_valid_claim_passes_without_network_io():
    ledger = FakeLedger({"blob1": Blob(http_status=200, raw_text="real source text")})

    verdict = await _grader(ledger).grade(_claim())

    assert verdict.ok
    assert verdict.code == ""
    assert verdict.diagnostics == {
        "deterministic": "passed",
        "deterministic_code": "",
        "evidence_count": 1,
        "source_count": 1,
        "fetched_source_count": 1,
        "dead_source_count": 0,
        "excerpt_chars": len("real source text"),
        "best_quote_score": 1.0,
        "quote_threshold": 0.92,
    }


# ---- 계산 클레임으로 가는 분기 (계약 §5) --------------------------------------


@dataclass
class _Reexecution:
    digest: str
    stdout: str


class _CountingReexecutor:
    def __init__(self, runs):
        self._runs = list(runs)
        self.calls = 0

    async def run(self, computation):
        self.calls += 1
        return self._runs.pop(0)


@dataclass
class _StoredClaim:
    id: str
    status: str = "verified"


class _ComputedLedger(FakeLedger):
    """계산 규칙이 더 보는 것: 전제 클레임과 그 출처 수."""

    def __init__(self, blobs, *, claims=None, sources=None):
        super().__init__(blobs)
        self._claims = claims or {}
        self._sources = sources or {}

    async def get_claim(self, claim_id):
        return self._claims.get(claim_id)

    async def claim_source_urls(self, claim_id):
        return list(self._sources.get(claim_id, []))


def _computed_claim(confidence=0.5):
    from neos.workflow.deep_analysis.models import ComputedEvidence

    return ProposedClaim(
        text="평균은 42.5 다",
        confidence=confidence,
        kind="computed",
        computation=ComputedEvidence(
            script_ref="f" * 64,
            inputs=["blob1"],
            premises=["c1"],
            runtime={"profile": "research-offline-v1", "image_digest": "sha256:x"},
            output_digest="e" * 64,
            claimed_value="42.5",
        ),
    )


def _computed_grader(ledger, reexecutor):
    return DeterministicGrader(
        ledger,
        quote_threshold=0.92,
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
        reexecutor=reexecutor,
    )


@pytest.mark.asyncio
async def test_a_computed_claim_takes_the_computed_rules():
    """quote 규칙이 돌면 `E_NO_EVIDENCE` 가 나온다 -- 증거가 `evidence` 가
    아니라 `computation` 에 있기 때문이다. 그 구별이 분기의 전부다."""
    ledger = _ComputedLedger({}, claims={"c1": _StoredClaim("c1")})

    verdict = await _computed_grader(ledger, _CountingReexecutor([])).grade(
        _computed_claim()
    )

    assert verdict.code == "E_COMPUTE_INPUT_UNFETCHED"


@pytest.mark.asyncio
async def test_a_quote_claim_still_takes_the_quote_rules():
    """분기가 생겨도 기존 경로는 그대로다."""
    verdict = await _grader(FakeLedger({})).grade(_claim(raw_ref="missing"))

    assert verdict.code == "E_SOURCE_DEAD"


@pytest.mark.asyncio
async def test_a_reproduced_computed_claim_passes_through_the_grader():
    ledger = _ComputedLedger(
        {"blob1": Blob(http_status=200, raw_text="body")},
        claims={"c1": _StoredClaim("c1")},
        sources={"c1": ["https://a"]},
    )
    runs = [
        _Reexecution("e" * 64, "평균: 42.5\n"),
        _Reexecution("e" * 64, "평균: 42.5\n"),
    ]

    verdict = await _computed_grader(ledger, _CountingReexecutor(runs)).grade(
        _computed_claim(confidence=0.5)
    )

    assert verdict.ok is True
