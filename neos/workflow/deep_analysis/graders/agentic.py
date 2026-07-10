"""의미 정합성 채점. det 통과분 중 티어링 대상만 심사(§6.5). judge 모델 ≠ worker 모델(A4)."""
from __future__ import annotations

import random

from ..llm import call_json, JSONParseError
from ..models import ProposedClaim, Verdict
from ..prompt_loader import render

_MAP = {
    "SUPPORTS": lambda r: Verdict(ok=True, label="SUPPORTS"),
    "PARTIAL": lambda r: Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL", detail=r),
    "UNRELATED": lambda r: Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED", detail=r),
    "CONTRADICTS": lambda r: Verdict(ok=False, code="E_CONTRADICTED", label="CONTRADICTS", detail=r),
}


class AgenticGrader:
    def __init__(self, *, judge_model, threshold, sample_rate,
                 llm_client=None, cassette=None, sampler=None):
        self.judge_model = judge_model
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.llm_client = llm_client
        self.cassette = cassette
        self.sampler = sampler or random.random

    def should_grade(self, value_est: float, confidence: float) -> bool:
        if value_est * confidence >= self.threshold:
            return True
        return self.sampler() < self.sample_rate

    async def grade(self, claim: ProposedClaim, value_est: float) -> Verdict:
        if not self.should_grade(value_est, claim.confidence):
            return Verdict(ok=True, label=None)
        evidence_block = "\n".join(
            f"<evidence>{e.excerpt}</evidence>" for e in claim.evidence
        ) or "(증거 없음)"
        prompt = render("judge", claim_text=claim.text, evidence_block=evidence_block)
        try:
            data, _ = await call_json(self.judge_model, prompt, max_tokens=300,
                                      client=self.llm_client, cassette=self.cassette)
        except JSONParseError:
            return Verdict(ok=True, label=None, detail="judge_unparseable")
        label = str(data.get("label", "")).upper()
        factory = _MAP.get(label)
        if factory is None:
            return Verdict(ok=True, label=None, detail="judge_unknown_label")
        return factory(str(data.get("rationale", "")))
