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
#
# Up to three leading spaces, per CommonMark. Applied to whole *lines* before
# any sentence splitting -- see `_uncited_stats`.
_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}\s")


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


def _uncited_stats(body: str) -> tuple[float, int, int, list[str]]:
    """Return (ratio, assertion count, uncited count, uncited sentences).

    The counts travel with the ratio because the ratio alone cannot be
    calibrated against: 1.00 over one assertion is a short report, 1.00 over
    forty is a badly cited one, and the two call for opposite fixes. 156
    recorded rejections stored only the code and so cannot distinguish them.

    The sentences travel too, for the retry loop (W3-h). A count tells the
    orchestrator that the draft failed; only the sentences let the next
    attempt fix the specific lines. They stay out of `diagnostics` on
    purpose -- `diagnostics` is what reaches the ledger, and report prose
    does not belong in an event payload.
    """

    # Headings come out *before* splitting, not after. `_sentences` cuts on
    # sentence-terminator punctuation, and a numbered heading carries one:
    # "### 2. 기준일(2026년 7월 19일) 시점의 상태" became
    # ["### 2.", "기준일(2026년 7월 19일) 시점의 상태"], and the second
    # fragment no longer starts with `#`, so filtering the *fragments* let it
    # through to be scored as an uncited assertion.
    #
    # W3-f filtered fragments and looked correct because its cases were
    # "### 1. 배경" -- the remainder held no digit and no Latin proper noun,
    # so it fell out of the denominator by accident. Any heading whose title
    # names a year or a product leaked. Measured 2026-08-09 over sample #5's
    # cassette: 1 of 11 reports crossed back under the threshold
    # (`94b0483c` 0.208 -> 0.116).
    prose = "\n".join(
        line for line in body.splitlines() if not _HEADING_LINE.match(line)
    )
    sentences = _sentences(prose)
    assertions = [
        s for s in sentences if _DIGIT.search(s) or _PROPER_NOUN.search(s)
    ]
    if not assertions:
        return 0.0, 0, 0, []
    uncited = [s for s in assertions if not _FOOTNOTE_REF.search(s)]
    return (
        len(uncited) / len(assertions),
        len(assertions),
        len(uncited),
        uncited,
    )




# A rejected draft's hints share the assembly prompt with the child summaries
# that the report is actually made of, and `clamp_prompt` drops child blocks
# to fit. Hints are capped so a badly cited draft cannot starve the next
# attempt of the very evidence it needs to cite.
_MAX_HINTED_SENTENCES = 8
_MAX_HINT_CHARS = 160

# The judge's rationale is model prose entering an event payload, so it is
# bounded. It is the judge's own assessment of a rendered report -- not
# fetched source text -- so the no-raw invariant this grader documents is
# untouched. The booleans beside it carry the part that aggregates; this is
# for reading one rejection.
_MAX_RATIONALE_CHARS = 400


def _uncited_hints(offenders: list[str]) -> list[str]:
    """Turn uncited sentences into instructions the next attempt can act on.

    Two ways out, and the second is the one that matters (W3-h): sentences
    reporting what could *not* be verified carry no citation because none
    exists, and they belong under the limits heading -- which `_report_body`
    already excludes from scoring. Sample #5's largest class of uncited
    sentences was exactly that ("검증된 클레임이 극히 제한적이어서 결론을 제시할
    수 없다"), written into the body where it gets scored. Naming the escape
    route beats teaching the grader to excuse the phrasing, which would only
    hand the model a way to dodge citations.
    """

    if not offenders:
        return []
    shown = offenders[:_MAX_HINTED_SENTENCES]
    lines = [
        f"다음 {len(offenders)}개 문장에 인용이 없다. 각각 입력에 있는 "
        "[C:claimid] 마커를 붙이거나, 뒷받침할 클레임이 없다면 "
        f"'## {_LIMITS_HEADING}' 절로 옮겨라:"
    ]
    for sentence in shown:
        text = sentence[:_MAX_HINT_CHARS].strip()
        suffix = "..." if len(sentence) > _MAX_HINT_CHARS else ""
        lines.append(f"- {text}{suffix}")
    if len(offenders) > len(shown):
        lines.append(f"- (그 외 {len(offenders) - len(shown)}개 문장)")
    return lines


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
        ratio, assertions, uncited, offenders = _uncited_stats(
            _report_body(report)
        )
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
                revision_hints=[
                    "리포트가 사실 주장을 하나도 담지 않았다. 입력의 verified "
                    "클레임을 인용해 본문을 작성하라."
                ],
            )

        if ratio >= threshold:
            return Verdict(
                ok=False,
                code="E_REPORT_UNCITED",
                detail=f"uncited assertion ratio {ratio:.2f} >= {threshold}",
                diagnostics=diagnostics,
                revision_hints=_uncited_hints(offenders),
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
                    revision_hints=[
                        "다음 하위 질문은 조사가 끝났는데 리포트가 다루지 "
                        f"않았다. 본문에서 답하라:\n{child.text}"
                    ],
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
            # The judge's account of *why* a draft that cleared every
            # deterministic check was still refused. It reached nowhere
            # before: the orchestrator logs `code` and `diagnostics`, never
            # `detail`, so every recorded E_REPORT_AGENTIC rejection said
            # only that the judge said no.
            #
            # The two booleans matter more than the prose. "Does not answer
            # the question" and "the evidence is too weak" are different
            # failures with different fixes, and they are structured -- they
            # aggregate across runs, which a rationale string cannot.
            # Sample #6 made this urgent: the judge became the dominant
            # rejection (8 of 18 gradings, up from 3) and not one of those 8
            # can be told apart today.
            return Verdict(
                ok=False,
                code="E_REPORT_AGENTIC",
                detail=rationale,
                diagnostics={
                    "judge": "ran",
                    "judge_answers_question": answers_question,
                    "judge_strength_ok": strength_ok,
                    "judge_rationale": rationale[:_MAX_RATIONALE_CHARS],
                },
                revision_hints=(
                    [f"판정자 반려 사유: {rationale}"] if rationale else []
                ),
            )
        # An approving judge has to say so. Recording nothing here is what
        # made a real approval indistinguishable in the ledger from the
        # degraded fallbacks above -- and sample #6's two gate passes were
        # both `judge: budget_exhausted`, so "the judge approved" and "the
        # judge never ran" is exactly the distinction that needs to survive.
        return Verdict(ok=True, diagnostics={"judge": "ran"})

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
