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
    def __init__(self, *, judge_model, threshold, sample_rate, max_output_tokens,
                 llm_client=None, cassette=None, sampler=None):
        self.judge_model = judge_model
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.max_output_tokens = max_output_tokens
        self.llm_client = llm_client
        self.cassette = cassette
        self.sampler = sampler or random.random

    def is_mandatory(self, value_est: float, confidence: float) -> bool:
        """전수 심사 대상(티어링 §6.5): value_est×confidence >= threshold.

        미만이면 샘플링 대상이며, 심사되지 않으면 미심사 통과된다.
        """
        return value_est * confidence >= self.threshold

    def should_grade(self, value_est: float, confidence: float) -> bool:
        if self.is_mandatory(value_est, confidence):
            return True
        return self.sampler() < self.sample_rate

    def _judge_failed(self, mandatory: bool, note: str) -> Verdict:
        """judge 판정 불가(파싱 실패/미지 라벨) 처리.

        D14: 저가치 **샘플링** 대상은 미심사 통과(label=None, ok=True)한다.
        단, **필수 심사 대상**(mandatory)은 자동 verified를 금지한다(§A4 인젝션
        방어): 적대적 페이지가 judge 출력을 깨뜨려 고가치 클레임을 무심사로
        통과시키는 경로를 닫는다. 대신 E_UNSUPPORTED로 반려해 재조사시키고,
        재시도 캡 소진 시 unverified→보고서 "한계" 섹션에 남긴다. Ledger가
        이 verdict을 claim_rejected/claim_unverified 이벤트로 기록한다.
        """
        if mandatory:
            return Verdict(
                ok=False,
                code="E_UNSUPPORTED",
                label=None,
                detail=f"{note}_mandatory",
                diagnostics={
                    "agentic": "attempted_rejected",
                    "agentic_label": None,
                },
            )
        return Verdict(
            ok=True,
            label=None,
            detail=note,
            diagnostics={
                "agentic": "attempted_passed",
                "agentic_label": None,
            },
        )

    async def grade(self, claim: ProposedClaim, value_est: float) -> Verdict:
        mandatory = self.is_mandatory(value_est, claim.confidence)
        if not mandatory and self.sampler() >= self.sample_rate:
            return Verdict(
                ok=True,
                label=None,
                diagnostics={"agentic": "skipped", "agentic_label": None},
            )
        evidence_block = "\n".join(
            f"<evidence>{e.excerpt}</evidence>" for e in claim.evidence
        ) or "(증거 없음)"
        prompt = render("judge", claim_text=claim.text, evidence_block=evidence_block)
        try:
            data, _ = await call_json(
                self.judge_model,
                prompt,
                max_tokens=self.max_output_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="claim_grading",
            )
        except JSONParseError:
            return self._judge_failed(mandatory, "judge_unparseable")
        label = str(data.get("label", "")).upper()
        factory = _MAP.get(label)
        if factory is None:
            return self._judge_failed(mandatory, "judge_unknown_label")
        verdict = factory(str(data.get("rationale", "")))
        verdict.diagnostics = {
            "agentic": (
                "attempted_passed" if verdict.ok else "attempted_rejected"
            ),
            "agentic_label": verdict.label,
        }
        return verdict
