"""Final report gate (§6.8): deterministic checks first, then agentic 2-judgment.

No-raw invariant: this grader only ever sees the rendered report text and the
root question text -- never blob raw text or the ledger's internal claim
store. P2: pure reads only, no ledger writes. The orchestrator (M4 Task 5)
drives the assembly-retry loop off this grader's `Verdict`.
"""

from __future__ import annotations

import re

from ..citation import OrphanCitationError
from ..llm import JSONParseError, TruncatedResponseError, call_json
from ..models import Verdict
from ..prompt_loader import render
from ..token_budget import TokenBudgetExhausted

# Post-CitationRender, every `[C:<claim_id>]` marker must have been rewritten
# to a footnote number. Any survivor means CitationRenderer never ran, or ran
# over stale text -- either way the report is not safe to ship.
_RAW_MARKER = re.compile(r"\[C:[0-9a-f]{8}\]")

_LIMITS_HEADING = "한계와 미확인 사항"

# Footnote reference left behind by CitationRenderer, e.g. "...text[3]".
_FOOTNOTE_REF = re.compile(r"\[\d+\]")

# Heuristic "factual assertion" signal: a digit, or an uppercase-initial
# proper-noun-like token (model/company/product names, acronyms, etc.).
_DIGIT = re.compile(r"\d")
_PROPER_NOUN = re.compile(r"\b[A-Z][A-Za-z]{2,}\b")

_SOURCE_HEADING = re.compile(r"(?m)^##\s*출처\s*$")

_UNCITED_RATIO_MAX = 0.20


def _report_body(report: str) -> str:
    """Everything before the '## 출처' footnote block, if present.

    The footnote list itself (`[1] https://...`) is not body prose and must
    not be scored by the uncited-assertion heuristic.
    """

    match = _SOURCE_HEADING.search(report)
    return report[: match.start()] if match else report


def _sentences(body: str) -> list[str]:
    """Crude sentence split: sentence-terminator punctuation or newlines.

    Intentionally simple (documented, per task brief) -- this is a soft gate,
    not a precision NLP heuristic.
    """

    parts = re.split(r"(?<=[.!?])\s+|\n+", body)
    return [p.strip() for p in parts if p.strip()]


def _uncited_ratio(body: str) -> float:
    sentences = _sentences(body)
    assertions = [
        s for s in sentences if _DIGIT.search(s) or _PROPER_NOUN.search(s)
    ]
    if not assertions:
        return 0.0
    uncited = [s for s in assertions if not _FOOTNOTE_REF.search(s)]
    return len(uncited) / len(assertions)


class ReportGrader:
    """Gates the final report before it can be handed back to the user."""

    def __init__(
        self,
        ledger,
        *,
        judge_model: str,
        llm_client=None,
        cassette=None,
        json_call=call_json,
    ) -> None:
        self.ledger = ledger
        self.judge_model = judge_model
        self.llm_client = llm_client
        self.cassette = cassette
        self.json_call = json_call

    async def grade_deterministic(self, report: str, root_id: str) -> Verdict:
        # (a) no raw [C:xxxxxxxx] markers may survive CitationRender.
        if _RAW_MARKER.search(report):
            return Verdict(
                ok=False,
                code=OrphanCitationError.code,
                detail="raw [C:...] marker found post-render",
            )

        # (b) marker-less factual-assertion ratio must stay under threshold.
        ratio = _uncited_ratio(_report_body(report))
        if ratio >= _UNCITED_RATIO_MAX:
            return Verdict(
                ok=False,
                code="E_REPORT_UNCITED",
                detail=f"uncited assertion ratio {ratio:.2f} >= {_UNCITED_RATIO_MAX}",
            )

        # (c) every resolved root-direct-child question must be mentioned.
        children = await self.ledger.children(root_id)
        for child in children:
            if child.status != "resolved":
                continue
            if child.text not in report:
                return Verdict(
                    ok=False,
                    code="E_REPORT_MISSING_QUESTION",
                    detail=f"resolved question not mentioned: {child.text}",
                )

        # (d) the limits/unresolved section must exist.
        if _LIMITS_HEADING not in report:
            return Verdict(
                ok=False,
                code="E_REPORT_NO_LIMITS",
                detail=f"missing '{_LIMITS_HEADING}' section",
            )

        return Verdict(ok=True)

    async def grade_agentic(self, report: str, root_text: str) -> Verdict:
        prompt = render("report_judge", report=report, root_text=root_text)
        try:
            data, _ = await self.json_call(
                self.judge_model,
                prompt,
                max_tokens=400,
                client=self.llm_client,
                cassette=self.cassette,
                stage="report_grading",
            )
        except TruncatedResponseError:
            # Rejecting here sends the orchestrator back to re-assemble the
            # draft (orchestrator.py:833-868), but a truncated judge has
            # nothing to do with draft quality -- the same judge cuts at the
            # same ceiling on every retry, burning report_retry_cap + 1
            # synthesizer calls to reach the same place. Treat it the way a
            # budget-exhausted judge is already treated below: fall back to
            # the deterministic verdict, and say why.
            return Verdict(ok=True, detail="judge_truncated")
        except JSONParseError:
            # Degrade to pass rather than halting the run (mirrors D14 in
            # AgenticGrader): an unparseable judge response is not evidence
            # of a bad report.
            return Verdict(ok=True, detail="judge_unparseable")

        answers_question = bool(data.get("answers_question", False))
        strength_ok = bool(data.get("strength_ok", False))
        rationale = str(data.get("rationale", ""))

        if not answers_question or not strength_ok:
            return Verdict(ok=False, code="E_REPORT_AGENTIC", detail=rationale)
        return Verdict(ok=True)

    async def grade(self, report: str, root_id: str) -> Verdict:
        deterministic = await self.grade_deterministic(report, root_id)
        if not deterministic.ok:
            return deterministic

        root = await self.ledger.get_question(root_id)
        if root is None:
            root = await self.ledger.root_question()
        root_text = root.text if root is not None else ""

        try:
            return await self.grade_agentic(report, root_text)
        except TokenBudgetExhausted:
            return deterministic
