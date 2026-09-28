"""의미 정합성 채점. det 통과분 중 티어링 대상만 심사(§6.5). judge 모델 ≠ worker 모델(A4)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..llm import call_json, JSONParseError, TruncatedResponseError
from ..models import ProposedClaim, Verdict
from ..prompt_loader import render

_MAP = {
    "SUPPORTS": lambda r: Verdict(ok=True, label="SUPPORTS"),
    "PARTIAL": lambda r: Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL", detail=r),
    "UNRELATED": lambda r: Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED", detail=r),
    "CONTRADICTS": lambda r: Verdict(ok=False, code="E_CONTRADICTED", label="CONTRADICTS", detail=r),
}


@dataclass(frozen=True)
class ComputedJudgeContext:
    """What the judge needs to read a computed claim (GRADE1, contract §5).

    A computed claim carries no excerpts -- its support is a re-executed
    script. Handed to the quote prompt, the judge saw "(증거 없음)" and could
    only answer UNRELATED, so a claim that had passed re-execution was
    rejected on the semantic tier. The contract gives the judge a narrower
    question for these: does the sentence stay within the value and its
    premises, and does the computation answer the question. The arithmetic is
    the deterministic grader's.

    `premises` pairs each premise claim's text with its verified excerpts.
    """

    question_text: str
    computed_value: str
    premises: tuple[tuple[str, tuple[str, ...]], ...]


def _premise_block(premises) -> str:
    lines = []
    for text, excerpts in premises:
        lines.append(f"<premise>{text}</premise>")
        lines.extend(f"<evidence>{excerpt}</evidence>" for excerpt in excerpts)
    return "\n".join(lines)


class AgenticGrader:
    def __init__(self, *, judge_model, threshold, sample_rate, max_output_tokens,
                 llm_client=None, cassette=None, sampler=None, judge_effort=None):
        self.judge_model = judge_model
        # 모델과 짝으로 주입받는다 -- 이 판정자가 부르는 모델에 대해 해석된 값이다.
        self.judge_effort = judge_effort
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

    @staticmethod
    def _diagnostics(state: str, label: str | None, tokens: int) -> dict:
        """진단 dict 하나 -- 오케스트레이터가 `claim_graded` 에 그대로 편다.

        `judge_tokens` 는 C3 의 절반짜리 해소다. 판정자는 `DAQuestion.spent_tokens`
        로 가는 채널이 **아예 없다** -- 성공한 판정도 실패한 판정도 워커의 집계에
        들지 않는다. 그래서 여기서 실패 경로만 세면 **실패만 집계되는 편향**이
        생긴다. 진짜 채널을 여는 것(`Verdict` → 질문 지출)은 `budgeter.should_stop()`
        이 보는 수를 바꾸므로 별도 결정이고, 그때까지는 §3.2 의 규율을 따른다:
        **고치기 전에 보이게 만든다.** 성공·실패 양쪽을 같은 키로 적어 두면
        판정이 태운 총량을 원장에서 뺄 수 있다.

        디스패치가 없었던 `skipped` 는 0 이다 -- 없는 호출과 공짜 호출을 같은
        수로 적는 것이 아니라, 없는 호출은 실제로 0 을 썼다.
        """
        return {
            "agentic": state,
            "agentic_label": label,
            "judge_tokens": tokens,
        }

    def _judge_failed(
        self, mandatory: bool, note: str, tokens: int = 0
    ) -> Verdict:
        """judge 판정 불가(파싱 실패/미지 라벨) 처리.

        D14: 저가치 **샘플링** 대상은 미심사 통과(label=None, ok=True)한다.
        단, **필수 심사 대상**(mandatory)은 자동 verified를 금지한다(§A4 인젝션
        방어): 적대적 페이지가 judge 출력을 깨뜨려 고가치 클레임을 무심사로
        통과시키는 경로를 닫는다. 대신 E_UNSUPPORTED로 반려해 재조사시키고,
        재시도 캡 소진 시 unverified→보고서 "한계" 섹션에 남긴다. Ledger가
        이 verdict을 claim_rejected/claim_unverified 이벤트로 기록한다.

        실패한 판정도 토큰을 태웠다 -- `tokens_spent` 는 `_diagnostics()` 의
        `judge_tokens` 와 같은 `tokens` 값을 쓴다 (C3-m1).
        """
        if mandatory:
            return Verdict(
                ok=False,
                code="E_UNSUPPORTED",
                label=None,
                detail=f"{note}_mandatory",
                diagnostics=self._diagnostics(
                    "attempted_rejected", None, tokens
                ),
                tokens_spent=tokens,
            )
        return Verdict(
            ok=True,
            label=None,
            detail=note,
            diagnostics=self._diagnostics("attempted_passed", None, tokens),
            tokens_spent=tokens,
        )

    async def grade(
        self,
        claim: ProposedClaim,
        value_est: float,
        *,
        computed: ComputedJudgeContext | None = None,
    ) -> Verdict:
        mandatory = self.is_mandatory(value_est, claim.confidence)
        if not mandatory and self.sampler() >= self.sample_rate:
            # 디스패치가 없었으므로 tokens_spent=0 -- judge_tokens 와 같은 값
            # (둘 다 리터럴 0).
            return Verdict(
                ok=True,
                label=None,
                diagnostics=self._diagnostics("skipped", None, 0),
                tokens_spent=0,
            )
        if claim.kind == "computed":
            if computed is None or not computed.premises:
                # Never judge a computed claim against an empty block: that
                # is the GRADE1 failure. The deterministic tier already
                # rejects computed claims without premises, so reaching here
                # means the caller did not pass the context -- a wiring bug,
                # rejected loudly rather than judged blind. Nothing was sent.
                return Verdict(
                    ok=False,
                    code="E_UNSUPPORTED",
                    label=None,
                    detail="computed_context_missing",
                    diagnostics=self._diagnostics("attempted_rejected", None, 0),
                    tokens_spent=0,
                )
            prompt = render(
                "judge_computed",
                question_text=computed.question_text,
                claim_text=claim.text,
                computed_value=computed.computed_value,
                premise_block=_premise_block(computed.premises),
            )
        else:
            evidence_block = "\n".join(
                f"<evidence>{e.excerpt}</evidence>" for e in claim.evidence
            ) or "(증거 없음)"
            prompt = render(
                "judge", claim_text=claim.text, evidence_block=evidence_block
            )
        try:
            data, response = await call_json(
                self.judge_model,
                prompt,
                max_tokens=self.max_output_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="claim_grading",
                effort=self.judge_effort,
            )
        except TruncatedResponseError as exc:
            # D24: a cut judgement is unfinished, not absent. D14's fail-open
            # answers "the judge produced garbage"; it does not answer "the
            # judge was interrupted mid-verdict". One measured response had
            # already emitted "label": "CONTRADICTS" before the cut, and the
            # fail-open turned that rejection into an acceptance. Mandatory or
            # sampled, a truncated judgement is rejected.
            return Verdict(
                ok=False,
                code="E_UNSUPPORTED",
                label=None,
                detail="judge_truncated",
                diagnostics=self._diagnostics(
                    "attempted_rejected", None, exc.tokens_spent
                ),
                tokens_spent=exc.tokens_spent,
            )
        except JSONParseError as exc:
            return self._judge_failed(
                mandatory, "judge_unparseable", exc.tokens_spent
            )
        tokens = response.input_tokens + response.output_tokens
        label = str(data.get("label", "")).upper()
        factory = _MAP.get(label)
        if factory is None:
            return self._judge_failed(mandatory, "judge_unknown_label", tokens)
        verdict = factory(str(data.get("rationale", "")))
        verdict.diagnostics = self._diagnostics(
            "attempted_passed" if verdict.ok else "attempted_rejected",
            verdict.label,
            tokens,
        )
        # 성공한 판정도 토큰을 태웠다 -- diagnostics 의 judge_tokens 와 반드시
        # 같은 값이어야 원장이 자기모순에 빠지지 않는다.
        verdict.tokens_spent = tokens
        return verdict
