"""Final report gate (§6.8): deterministic checks first, then agentic 2-judgment.

No-raw invariant: this grader only ever sees the rendered report text and the
root question text -- never blob raw text or the ledger's internal claim
store. P2: pure reads only, no ledger writes. The orchestrator (M4 Task 5)
drives the assembly-retry loop off this grader's `Verdict`.
"""

from __future__ import annotations

import re
from dataclasses import replace

from neos.config.settings import settings

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

# The limits section lists what could NOT be verified. By construction no
# verified claim stands behind those lines, so demanding a citation on them
# is an impossible requirement -- the same reason the footnote block is
# excluded below. It only became visible once W3-e made the section always
# present: sample #4's `cb1593f2` scored 0.455 with it and 0.353 without.
_LIMITS_SCORING_BOUNDARY = re.compile(
    r"(?m)^##\s*" + re.escape(_LIMITS_HEADING) + r"\s*$"
)

# A markdown heading is a label, not a factual assertion. `_sentences` splits
# on newlines, so "### 1. 배경" became its own "sentence"; the digit in it
# then satisfied `_DIGIT` and it was counted as an uncited claim. Measured
# 2026-08-08 (sample #4): 1-7 of each run's uncited items were heading
# fragments, and excluding them moved `93795eaf` 0.348 -> 0.167 and
# `2ff4761c` 0.333 -> 0.143, both under the 0.20 threshold.
_HEADING_LINE = re.compile(r"^#{1,6}\s")


def _report_body(report: str) -> str:
    """The prose that a citation gate may fairly score.

    Excludes the '## 출처' footnote block (a list of URLs is not prose) and
    the limits section (a list of things that could not be verified cannot
    carry citations). Whichever comes first wins, so the order the model
    emits them in does not change the score.
    """

    cuts = [
        match.start()
        for match in (
            _SOURCE_HEADING.search(report),
            _LIMITS_SCORING_BOUNDARY.search(report),
        )
        if match is not None
    ]
    return report[: min(cuts)] if cuts else report


def _sentences(body: str) -> list[str]:
    """Crude sentence split: sentence-terminator punctuation or newlines.

    Intentionally simple (documented, per task brief) -- this is a soft gate,
    not a precision NLP heuristic.
    """

    parts = re.split(r"(?<=[.!?])\s+|\n+", body)
    return [p.strip() for p in parts if p.strip()]


def _uncited_stats(body: str) -> tuple[float, int, int]:
    """Return (ratio, assertion count, uncited count).

    The counts travel with the ratio because the ratio alone cannot be
    calibrated against: 1.00 over one assertion is a short report, 1.00 over
    forty is a badly cited one, and the two call for opposite fixes. 156
    recorded rejections stored only the code and so cannot distinguish them.
    """

    sentences = _sentences(body)
    assertions = [
        s
        for s in sentences
        if not _HEADING_LINE.match(s)
        and (_DIGIT.search(s) or _PROPER_NOUN.search(s))
    ]
    if not assertions:
        return 0.0, 0, 0
    uncited = [s for s in assertions if not _FOOTNOTE_REF.search(s)]
    return len(uncited) / len(assertions), len(assertions), len(uncited)




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
        threshold = settings.config.deep_analysis.report_uncited_ratio_max
        ratio, assertions, uncited = _uncited_stats(_report_body(report))
        # Carried by every verdict from here on, not only the rejection:
        # recording the failing side alone yields a distribution censored at
        # the threshold, which cannot say whether the cut is in the right
        # place.
        diagnostics = {
            "uncited_ratio": round(ratio, 4),
            "uncited_assertions": assertions,
            "uncited_count": uncited,
            "uncited_threshold": threshold,
        }
        # (b0) a report that asserts nothing is not a well-cited report --
        # it is an absent one, and it must not borrow the perfect score that
        # an empty ratio produces. D-2, decided 2026-08-08 on sample #2:
        # 5 of 18 gradings scored 0.00 with `assertions == 0`, and one of
        # those reports (`a82648e3`) was the empty string. What stopped it
        # was `E_REPORT_NO_LIMITS` -- a *formatting* check for the "한계와
        # 미확인 사항" heading. Had the model emitted that heading, a report
        # with no content would have cleared every substantive check.
        #
        # A dedicated code rather than folding into E_REPORT_UNCITED, for the
        # reason `_uncited_stats` already documents: 1.00 over one assertion
        # and 1.00 over forty call for opposite fixes, and so do "said
        # nothing" and "cited nothing".
        if assertions == 0:
            return Verdict(
                ok=False,
                code="E_REPORT_EMPTY",
                detail="report contains no factual assertion to cite",
                diagnostics=diagnostics,
            )

        if ratio >= threshold:
            return Verdict(
                ok=False,
                code="E_REPORT_UNCITED",
                detail=f"uncited assertion ratio {ratio:.2f} >= {threshold}",
                diagnostics=diagnostics,
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
                    diagnostics=diagnostics,
                )

        # (d) the limits/unresolved section must exist.
        if _LIMITS_HEADING not in report:
            return Verdict(
                ok=False,
                code="E_REPORT_NO_LIMITS",
                detail=f"missing '{_LIMITS_HEADING}' section",
                diagnostics=diagnostics,
            )

        return Verdict(ok=True, diagnostics=diagnostics)

    async def grade_agentic(self, report: str, root_text: str) -> Verdict:
        prompt = render("report_judge", report=report, root_text=root_text)
        try:
            data, _ = await self.json_call(
                self.judge_model,
                prompt,
                max_tokens=settings.config.deep_analysis.report_judge_max_output_tokens,
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
            #
            # `detail` is useful in-process, but the orchestrator's
            # `report_graded` event only persists `verdict.diagnostics`
            # (orchestrator.py:886-902) -- without a diagnostics key this
            # degraded mode is byte-identical in the ledger to a judge that
            # ran and approved.
            return Verdict(
                ok=True,
                detail="judge_truncated",
                diagnostics={"judge": "truncated"},
            )
        except JSONParseError:
            # Degrade to pass rather than halting the run (mirrors D14 in
            # AgenticGrader): an unparseable judge response is not evidence
            # of a bad report. Same durability note as above.
            return Verdict(
                ok=True,
                detail="judge_unparseable",
                diagnostics={"judge": "unparseable"},
            )

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
            agentic = await self.grade_agentic(report, root_text)
        except TokenBudgetExhausted:
            # Same fallback as before, but no longer indistinguishable from a
            # judge that ran and approved. P2 keeps this grader read-only, so
            # the marker rides the verdict to the orchestrator's event.
            #
            # `detail` alone does not survive: the orchestrator's
            # `report_graded` sink (orchestrator.py:886-902) logs `ok`,
            # `attempt`, `code`, and `**verdict.diagnostics` -- it never reads
            # `detail`. `diagnostics` is what actually reaches the ledger, so
            # the marker has to ride there, not just on `detail`.
            return replace(
                deterministic,
                detail="judge_budget_exhausted",
                diagnostics={
                    **deterministic.diagnostics,
                    "judge": "budget_exhausted",
                },
            )
        # The agentic verdict is the answer, but the deterministic gate's
        # measurements have to survive it: reports that reach the judge are
        # exactly the ones that cleared the uncited cut, so dropping their
        # ratios here would leave only rejections on record and make the
        # threshold impossible to evaluate.
        agentic.diagnostics = {**deterministic.diagnostics, **agentic.diagnostics}
        return agentic
