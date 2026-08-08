"""Shared component contracts for the Deep Analysis Harness."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Effort(Enum):
    SCOUT = "scout"
    DIG = "dig"
    SPLIT = "split"
    SYNTH = "synth"


@dataclass
class Assignment:
    question_id: str
    brief: str
    effort: Effort
    repairs: list = field(default_factory=list)
    # 검색어로 쓸 원 질문. brief는 템플릿이 렌더링된 프롬프트 전문(~1KB)이라
    # 그대로 검색하면 결과가 0건이다. 비어 있으면 워커가 brief로 되돌아간다.
    question_text: str = ""


@dataclass
class ProposedBlob:
    """Content-addressed fetch output proposed by a stateless worker."""

    content_hash: str
    source_url: str
    http_status: int
    raw_text: str


@dataclass
class ProposedEvidence:
    source_url: str
    excerpt: str
    raw_ref: str


@dataclass
class ProposedClaim:
    text: str
    confidence: float
    evidence: list[ProposedEvidence] = field(default_factory=list)


@dataclass
class EntailmentOutcome:
    """Result of applying one entailment batch.

    ``discarded`` carries the claims the batch dropped so the orchestrator can
    record them. A ``narrow`` action is not a discard — the narrowed claim
    appears in ``refined``.
    """

    refined: list[ProposedClaim] = field(default_factory=list)
    discarded: list[ProposedClaim] = field(default_factory=list)


@dataclass
class RepairResult:
    claim_id: str
    action: Literal["fixed", "weakened", "abandoned"]
    new_text: str | None = None
    new_evidence: list[ProposedEvidence] = field(default_factory=list)


@dataclass
class WorkerResult:
    question_id: str
    status: Literal["completed", "partial", "failed"]
    claims: list[ProposedClaim] = field(default_factory=list)
    discarded_claims: list[ProposedClaim] = field(default_factory=list)
    blobs: list[ProposedBlob] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)
    proposed_subquestions: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    tokens_spent: int = 0
    model: str = ""
    self_assessment: float = 0.0
    fail_reason: str = ""
    confidence_clamped_count: int = 0
    confidence_clamped_by_source_count: dict[str, int] = field(
        default_factory=dict
    )
    # entailment 배치가 필터를 적용하지 못하고 원본 claim을 그대로 통과시켰는가.
    # discard 0건의 두 원인("버릴 게 없었다" / "필터가 안 돌았다")을 가른다.
    entailment_skipped: bool = False


@dataclass
class Verdict:
    ok: bool
    code: str = ""
    detail: str = ""
    salvage: str | None = None
    label: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # What the next attempt should change, in the rejected draft's own words
    # (W3-h). In-process only: the orchestrator logs `code` and
    # `diagnostics`, never this, so report prose stays out of the ledger.
    revision_hints: list[str] = field(default_factory=list)


@dataclass
class ConflictNote:
    claim_a: str
    claim_b: str
    nature: str


@dataclass
class NodeSummary:
    question_id: str
    answer: str
    key_claim_ids: list[str]
    confidence: float
    caveats: list[str]
    conflicts: list[ConflictNote] = field(default_factory=list)
