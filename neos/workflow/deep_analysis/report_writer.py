"""Report writing for a deep-analysis run: assemble (or compose) → render → grade,
retried up to `report_retry_cap`, never empty-handed (§6.8).

Moved verbatim from `Orchestrator._finalize` (2026-10-08). This module provides
reduction plus conflict resolution as `reduce_and_resolve` and report writing as
`ReportWriter`; the Orchestrator decides on and runs the reinvestigation round
(it needs a round) and owns the run loop. `ReportWriter` owns everything from
"here are the summaries" to the delivered text.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

from neos.config.settings import settings

from neos.coding.sandbox.base import SandboxLimits

from .citation import OrphanCitationError
from .conflict import resolve_conflicts
from .models import NodeSummary, Verdict
from .research_session import CommandLimits
from .token_budget import TokenBudgetExhausted


_LIMITS_HEADING = "## 한계와 미확인 사항"
# Harness-owned, like `_LIMITS_HEADING` and CitationRenderer's `## 출처`.
# `graders/report.py` mirrors this string in its scoring boundaries.


_QUESTIONS_HEADING = "## 조사한 하위 질문"

# 원장 어휘 -> 독자 문장. 강등 사유는 `node_reduction_degraded` /
# `report_assembly_degraded` 이벤트의 `reason` 이고, 그 기계 문자열이
# `NodeSummary.caveats` 를 타고 리포트의 한계 절까지 그대로 흘렀다.
#
# 표본 #9 의 배달된 리포트에 `- input_bound` 라는 줄이 **51회** 찍혔고,
# 판정자가 그것을 반려 사유로 인용했다 -- "다수의 '미확인'·'input_bound'
# 항목이 남아 실질적 종합이 이루어지지 않았다".
#
# 원장 쪽 문자열은 건드리지 않는다. D28 이 정지 사유를 기계가 읽을 수 있게
# 만들려고 싸운 자리이고, 경계 전후 집계도 그 어휘에 걸려 있다. 바꾸는 것은
# **독자에게 보여줄 때뿐**이다.
_DEGRADATION_PROSE = {
    "input_bound": (
        "이 하위 질문의 요약은 입력이 한도를 넘어 축약본으로 대체되었습니다."
    ),
    "token_budget_exhausted": (
        "전체 토큰 예산이 소진되어 이 하위 질문을 끝까지 요약하지 못했습니다."
    ),
    "tier_floor": (
        "남은 토큰 예산이 부족해 이 하위 질문을 끝까지 요약하지 못했습니다."
    ),
    "empty_assembly": ("본문 조립이 비어 있어 결정론적 템플릿으로 대체되었습니다."),
}


def _reader_facing_caveats(caveats: list[str]) -> list[str]:
    """Translate ledger vocabulary and drop repeats, for the limits section.

    Dedup matters as much as the wording: one run degraded 18 nodes for the
    same reason, so the section repeated a single line 18 times. Order is
    preserved -- the first occurrence keeps its place.
    """

    seen: set[str] = set()
    out: list[str] = []
    for caveat in caveats:
        text = _DEGRADATION_PROSE.get(caveat, caveat)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


# How far each rejection code got through `grade_deterministic`, in the order
# that grader applies its checks. A draft refused later cleared every check
# before it, so this is a fact about the gate rather than a judgement call.
# `E_REPORT_AGENTIC` sits highest: it cleared all four deterministic checks
# and only the LLM judge objected.
_GATE_DEPTH = {
    "E_ORPHAN_CITE": 0,
    "E_REPORT_EMPTY": 1,
    "E_REPORT_UNCITED": 2,
    "E_REPORT_MISSING_QUESTION": 3,
    "E_REPORT_NO_LIMITS": 4,
    "E_REPORT_AGENTIC": 5,
}


def _best_rejected_draft(rejected: list[tuple[Verdict, str]]) -> str | None:
    """Pick which refused draft the user actually receives.

    Every attempt was rejected, so this does not change the pass rate --
    it changes what a failed run hands back. Today the loop keeps whichever
    draft came last, and sample #5 shows the cost: `94b0483c` produced
    drafts scoring 0.140 and 0.095 (both under the 0.20 citation cut, both
    stopped by the agentic judge) and then shipped its third at 0.208. The
    two better drafts were discarded for no reason other than arrival order.

    Returns the chosen report text, or None when nothing was ever graded
    (every attempt orphaned before rendering) -- the caller falls back.

    Ranked lexicographically on the gate's own measurements, in this order:

    1. **How far it got** (`_GATE_DEPTH`). The only term that is a recorded
       fact rather than a comparison: an `E_REPORT_AGENTIC` rejection cleared
       all four deterministic checks, an `E_REPORT_UNCITED` one died at the
       second.
    2. **Uncited ratio**, lower first. The one judgement here. A
       cap-exhausted report already ships labelled unresolved, so the thing
       that does real damage in it is an unsupported assertion -- safety
       over length.
    3. **Assertion count**, higher first, so that between equally-cited
       drafts the substantive one wins.

    The obvious trap -- a two-assertion draft with a perfect ratio beating a
    forty-assertion one -- is mostly unreachable: a draft that scores 0.0 and
    clears the remaining checks *passes the gate* and returns, so it never
    arrives here. Anything in this list died to a later check, and term 1
    sorts that out first. What remains is the narrow case where a short
    fully-cited draft and a long partly-cited one fail the *same* check;
    there the short one wins, which is term 2 doing what it says.

    Measured against sample #5's five failing runs: 3 improved, 2 unchanged,
    0 worse. `94b0483c` swaps a 0.208/UNCITED draft for a 0.095/AGENTIC one;
    `d8cda7c5` swaps 0.250 over 12 assertions for 0.235 over 17.

    `diagnostics` can be empty (the orphan-marker branch skips grading
    entirely), so every field is read with a pessimistic default.
    """

    if not rejected:
        return None

    def rank(item: tuple[Verdict, str]) -> tuple[int, float, int]:
        verdict, _report = item
        diagnostics = verdict.diagnostics
        return (
            _GATE_DEPTH.get(verdict.code, 0),
            -diagnostics.get("uncited_ratio", 1.0),
            diagnostics.get("uncited_assertions", 0),
        )

    # `max` keeps the first of equal-ranked items, so a later attempt has to
    # actually score better to displace an earlier one -- ties do not drift
    # toward whichever draft happened to come last.
    return max(rejected, key=rank)[1]


def _ensure_limits_section(report: str, caveats: list[str]) -> str:
    """Guarantee the report's required limits section, from what we already know.

    The prompt asks the model for it (`final_compose.md`, 필수 섹션 3/4), and the
    model never got that far. Measured across three live samples: 54 of 54
    assemblies stopped exactly at their output ceiling -- including after
    W3-d's expansion retry, which fired 18 times and was cut 18 times. The
    section sits near the end of the template, so truncation kills it first,
    every time.

    Twice now that has been the only thing standing between a report and the
    gate: `dd8dc763` #2 (uncited 0.267) and `a38d441a` #2 (uncited 0.191,
    under the 0.20 threshold) both cleared the citation bar and were rejected
    with `E_REPORT_NO_LIMITS`.

    `## 출처` never had this problem because CitationRenderer appends it --
    the harness owns it. The limits section is the same kind of obligation
    and its content (`caveats`) is already in `_finalize`'s hand, gathered by
    `_collect_caveats`. Asking a truncated model to dictate back something we
    already hold is the mistake; structural completeness is the harness's job.

    Nothing is invented: with no caveats the section says so explicitly
    rather than implying a clean bill of health.
    """
    if _LIMITS_HEADING in report:
        return report
    body = "\n".join(f"- {item}" for item in caveats) or "- (기록된 미확인 항목 없음)"
    return f"{report.rstrip()}\n\n{_LIMITS_HEADING}\n{body}\n"


def _ensure_question_coverage(report: str, child_summaries: list[NodeSummary]) -> str:
    """Guarantee that every resolved sub-question is named in the report.

    Third harness-owned section, for the same reason as the other two
    (W3-l). The gate requires each `resolved` child question to appear in
    the report, and asking the model to reproduce it never worked: a
    sub-question is an interrogative *plus a sourcing directive*
    ("...원문에서 ...을 확인하라"), 128-213 characters of it, and the
    composer reliably copies the question and drops the directive. Sample
    #8 measured the result -- `E_REPORT_MISSING_QUESTION` became the
    dominant rejection at 5 of 15 gradings, and `da8e7ba6` lost three
    reports carrying 27-30 assertions with 0-2 uncited to it.

    Matching on the interrogative alone was the cheap alternative and the
    measurement rejected it: it resolves 1 of the 3 failing questions.

    Only the questions go in, never the answers -- the body already holds
    those, and duplicating them would inflate the report and its uncited
    count. That also makes this section the same *kind* of text as the
    limits section: a list, not a set of factual assertions, which is why
    `graders/report.py` excludes both from citation scoring.
    """

    resolved = [
        summary
        for summary in child_summaries
        if summary.question_status == "resolved" and summary.question_text
    ]
    if not resolved or _QUESTIONS_HEADING in report:
        return report
    missing = [s for s in resolved if s.question_text not in report]
    if not missing:
        return report
    body = "\n".join(f"- {s.question_text}" for s in missing)
    return f"{report.rstrip()}\n\n{_QUESTIONS_HEADING}\n{body}\n"


class ReportWriter:
    def __init__(
        self,
        ledger,
        synthesizer,
        citation_renderer,
        report_grader,
        *,
        sandbox_provider=None,
        compose_runtime_factory=None,
        checkpoint=None,
    ) -> None:
        self.ledger = ledger
        self.synthesizer = synthesizer
        self.citation_renderer = citation_renderer
        self.report_grader = report_grader
        self.sandbox_provider = sandbox_provider
        self.compose_runtime_factory = compose_runtime_factory
        self._checkpoint_fn = checkpoint

    async def _checkpoint(self) -> None:
        if self._checkpoint_fn is not None:
            result = self._checkpoint_fn()
            if inspect.isawaitable(result):
                await result

    async def write(
        self, root_id: str, summaries: dict[str, NodeSummary]
    ) -> str:
        config = settings.config.deep_analysis
        root_summary = summaries.get(root_id)
        if root_summary is None:
            root_summary = NodeSummary(
                question_id=root_id,
                answer="",
                key_claim_ids=[],
                confidence=0.0,
                caveats=[],
            )
        child_summaries = await self._child_summaries(root_id, summaries)
        caveats = await collect_caveats(self.ledger, summaries)
        await self._checkpoint()

        cap = config.report_retry_cap
        last: str | None = None
        # The last draft that survived citation rendering. `last` is the raw
        # assembly output and still carries `[C:xxxxxxxx]` markers, which are
        # internal claim addresses -- not citations a reader can follow.
        last_rendered: str | None = None
        # What the previous attempt was rejected for (W3-h). Empty on the
        # first pass. Without this the loop re-rolled the identical prompt:
        # `assemble` got the same three arguments every time, so the three
        # attempts were three independent samples rather than a correction.
        # Sample #5 shows the consequence -- 18 gradings, and the uncited
        # ratios wander instead of falling (`4098117c` .357 -> .500 -> .267,
        # `d8cda7c5` .316 -> .235 -> .250). Two of `94b0483c`'s drafts had
        # already cleared the citation cut and the third undid it.
        revision_hints: list[str] = []
        # Every rendered draft the gate refused, with the verdict that
        # refused it. Feeds `_best_rejected_draft` once the cap is spent.
        rejected: list[tuple[Verdict, str]] = []
        for attempt in range(cap + 1):
            if settings.config.deep_analysis.compose_child_enabled:
                # J4 (D105): 초안을 compose 자식이 쓴다. 렌더러·게이트·재시도는 아래 그대로다.
                draft = await self._compose_draft(
                    root_id,
                    root_summary,
                    child_summaries,
                    caveats,
                    revision_hints=revision_hints,
                    attempt=attempt,
                )
                if draft is None:
                    # 실패는 `_compose_draft` 가 원장에 남겼다. 옛 조립기로 슬쩍 떨어지지 않는다 --
                    # 그러면 "compose 로 돌았다" 고 믿는 표본이 사실은 섞여 돈다.
                    continue
            else:
                draft = await self.synthesizer.assemble(
                    root_summary,
                    child_summaries,
                    caveats,
                    revision_hints=revision_hints,
                )
            last = draft
            # The limits section joins the draft *before* rendering, so its
            # markers are resolved by the same pass as the body's (W3-k).
            #
            # It used to be appended to the already-rendered report, which
            # meant CitationRenderer never saw it. `node_summary.md` tells
            # the model to mark every factual assertion, and the model
            # obliges in its `caveats` too -- 3 of sample #7's 30 node
            # summaries did. Those raw `[C:xxxxxxxx]` markers rode straight
            # into the final text, where `grade_deterministic`'s check (a)
            # rejected the whole report for carrying them.
            #
            # It only fired when the harness actually appended the section:
            # a degraded assembly emits the heading itself, `_ensure_limits_
            # section` then skips, and the run survived. That is exactly the
            # observed shape -- `03dd8ddd` and `ba84c409` orphaned on
            # attempts 0 and 1 and not on the degraded attempt 2.
            #
            # Safe against the obvious worry: a caveat may only cite claims
            # the renderer can resolve, and all 12 caveat-referenced claims
            # across samples #6 and #7 were `verified`. One that is not still
            # raises here, which is the correct answer rather than shipping
            # an unresolvable marker.
            draft = _ensure_limits_section(draft, caveats)
            # Same pre-render placement, same reason (D44): anything the
            # harness appends after rendering carries its markers raw.
            draft = _ensure_question_coverage(draft, child_summaries)
            try:
                report = await self.citation_renderer.render(draft)
            except OrphanCitationError as exc:
                # The offending claim id, or the ledger cannot say what went
                # wrong. Sample #6 produced the first three E_ORPHAN_CITE
                # rejections in the ledger's history, all in one run
                # (`36903adc`), and the cause was not recoverable after the
                # fact: replaying the cassette showed that run's drafts cited
                # only its own *verified* claims, so the recorded event ruled
                # nothing in or out. `CitationRenderer` raises with the claim
                # id already in hand -- it just was not being written down.
                await self.ledger.log(
                    "report_graded",
                    root_id,
                    {
                        "ok": False,
                        "code": OrphanCitationError.code,
                        "attempt": attempt,
                        "orphan_claim_id": exc.claim_id,
                    },
                )
                # This branch skips grading, so without its own hint the
                # next attempt would inherit whatever the *previous*
                # rejection said -- or nothing at all on attempt 0.
                revision_hints = [
                    "인용 마커가 입력에 없는 claim id 를 가리켰다. 입력의 "
                    "[C:claimid] 목록에 있는 id 만 사용하라."
                ]
                continue  # AC-c: orphan citation → re-assemble
            # Still guaranteed after rendering, for the case the renderer
            # itself is a stand-in that returns text without the section.
            # Idempotent: the pre-render call above normally satisfies it.
            report = _ensure_limits_section(report, caveats)
            report = _ensure_question_coverage(report, child_summaries)
            last_rendered = report
            verdict = (
                await self.report_grader.grade(report, root_id)
                if self.report_grader is not None
                else Verdict(ok=True)
            )
            # The gate's own measurements ride along so the threshold can be
            # evaluated after the fact. Spread rather than nested: an event
            # consumer aggregating these should not have to know they were
            # once a sub-object. Empty when the grader measured nothing, and
            # then nothing is added.
            if verdict.ok:
                await self.ledger.log(
                    "report_graded",
                    root_id,
                    {"ok": True, "attempt": attempt, **verdict.diagnostics},
                )
                await self.ledger.complete_run()
                return report
            await self.ledger.log(
                "report_graded",
                root_id,
                {
                    "ok": False,
                    "code": verdict.code,
                    "attempt": attempt,
                    **verdict.diagnostics,
                },
            )
            # Only the verdict's diagnostics reach the ledger above; the
            # hints carry the rejected draft's own sentences and stay in
            # process, feeding the next iteration's prompt.
            revision_hints = verdict.revision_hints
            rejected.append((verdict, report))

        # Cap exhausted — no empty-handed exit (§6.8): attach a failure
        # appendix to the last draft that rendered.
        #
        # This used to ship `last`, the raw assembly output. Every run of the
        # 2026-08-07 live sample left by this path (the gate rejected 18 of 18
        # attempts), so every report handed to a user carried raw
        # `[C:da8b7072]` markers and no `## 출처` list -- an internal claim
        # address where a citation belonged. The rendered text is also the
        # exact text the grader judged, so the `uncited_ratio` recorded in the
        # ledger now describes what was actually delivered.
        #
        # When every attempt orphaned there is no rendered text at all, and
        # `last` (the raw draft) used to ship as-is. Sample #17's run
        # `9d9daa8b` left by that path with **32 raw markers and zero
        # footnotes** -- W3-a's failure, back again (ORPHAN1).
        #
        # `render_best_effort` narrows that: one invented claim id no longer
        # costs the report every *other* citation it earned. The orphan
        # markers stay visible on purpose -- D10 rejected substituting them
        # away, because removing the raw marker hides the integrity failure
        # instead of reporting it. So the appendix names them instead.
        chosen = _best_rejected_draft(rejected)
        reason = "조립/채점 재시도 캡 소진."
        if last is None and settings.config.deep_analysis.compose_child_enabled:
            # D114: compose 자식이 **모든** 시도에서 초안을 내지 못했다. 그대로면 사용자는 부록 한 줄만
            # 받는다(#29 `196c9173`, D113). 옛 조립기를 **한 번, 루프 밖에서** 부른다 -- 루프 안의 시도를
            # 바꾸면 compose 의 재시도 기회가 줄고, 조용히 바꾸면 "compose 로 돌았다" 는 표본이 섞인다.
            # 그래서 원장에 이름을 남기고, 부록에도 적고, 채점은 하지 않는다(캡은 이미 썼다).
            await self.ledger.log(
                "report_assembly_degraded",
                root_id,
                {"reason": "compose_all_attempts_failed", "attempts": cap + 1},
            )
            last = await self.synthesizer.assemble(
                root_summary,
                child_summaries,
                caveats,
                revision_hints=revision_hints,
            )
            last = _ensure_question_coverage(
                _ensure_limits_section(last, caveats), child_summaries
            )
            reason = (
                "조립/채점 재시도 캡 소진. compose 자식이 모든 시도에서 리포트를 내지 못해 "
                "옛 조립기의 초안을 실었다 -- 이 초안은 채점되지 않았다."
            )
        best = chosen or last_rendered
        if best is None and last:
            best, orphans = await self.citation_renderer.render_best_effort(last)
            if orphans:
                await self.ledger.log(
                    "report_assembly_degraded",
                    root_id,
                    {"reason": "orphan_citations_delivered", "orphans": orphans},
                )
                # 앞의 사유(캡 소진 · compose 대체)에 덧붙인다 -- 옛 경로에서는 바이트가 같다.
                reason += (
                    " 그리고 조립기가 존재하지 않는 "
                    f"클레임 id 를 인용했다({', '.join(orphans)}) -- 본문에 남은 "
                    "`[C:...]` 표기는 각주로 해소되지 못한 내부 주소이며 "
                    "출처가 아니다."
                )
        report = (best or "") + f"\n\n## 부록: 미해결 사유\n{reason}"
        await self.ledger.complete_run()
        return report

    async def _child_summaries(
        self, root_id: str, summaries: dict[str, NodeSummary]
    ) -> list[NodeSummary]:
        out: list[NodeSummary] = []
        for child in await self.ledger.children(root_id):
            if getattr(child, "status", None) == "abandoned":
                continue
            summary = summaries.get(child.id)
            if summary is not None:
                # Carry the question's own wording into assembly (W3-i). The
                # report gate requires every *resolved* child question to be
                # mentioned, but the composer's input was
                # `- [{question_id}] {answer}` -- it had never seen the
                # question text it was being asked to reproduce, so the check
                # could not be satisfied. Sample #5's `6e65093e` failed it
                # 3/3 with an uncited ratio of 0.063, the best-cited run in
                # the sample after the one that passed.
                out.append(
                    replace(
                        summary,
                        question_text=getattr(child, "text", "") or "",
                        question_status=getattr(child, "status", "") or "",
                    )
                )
        return out

    async def _compose_draft(
        self,
        root_id: str,
        root_summary: NodeSummary,
        child_summaries: list[NodeSummary],
        caveats: list[str],
        *,
        revision_hints: list[str],
        attempt: int,
    ) -> str | None:
        """J4 (D105). compose 자식에게 초안을 받는다. 실패면 원장에 이유를 남기고 None."""
        from .compose_worker import ComposeFailed, run_compose_worker
        from .subagent_adapter import compose_model_pin
        from .synthesizer import assembly_child_blocks

        research = settings.config.deep_analysis.code_research
        missing = (
            "sandbox_provider_missing"
            if self.sandbox_provider is None
            else "compose_runtime_factory_missing"
            if self.compose_runtime_factory is None
            else None
        )
        await self.ledger.log(
            "code_worker_started",
            root_id,
            {"spec": "compose", "profile": research.sandbox_profile, "run_id": "", "attempt": attempt},
        )
        if missing is not None:
            await self.ledger.log(
                "code_worker_unsubmitted",
                root_id,
                {"reason": missing, "spec": "compose", "attempt": attempt},
            )
            return None
        root = await self.ledger.root_question()
        try:
            text, summary = await run_compose_worker(
                ledger=self.ledger,
                provider=self.sandbox_provider,
                root_id=root_id,
                root_text=str(getattr(root, "text", "") or ""),
                root_summary=root_summary.answer,
                child_blocks=assembly_child_blocks(child_summaries),
                caveats=caveats,
                revision_hints=revision_hints,
                runtime_factory=self.compose_runtime_factory,
                model=compose_model_pin(),
                parent_id=str(self.ledger.run_id),
                attempt=attempt,
                limits=SandboxLimits.safe_defaults(),
                command_limits=CommandLimits(
                    timeout_sec=research.reexecution.cpu_sec,
                    output_bytes=research.reexecution.stdout_bytes,
                ),
                max_turns=settings.config.deep_analysis.compose_max_turns,
                profile=research.sandbox_profile,
            )
        except TokenBudgetExhausted:
            raise
        except ComposeFailed as exc:
            reason = exc.reason
        except Exception as exc:  # noqa: BLE001 -- 이름을 남기고 다음 시도로 간다
            reason = type(exc).__name__
        else:
            await self.ledger.log(
                "code_worker_submitted",
                root_id,
                {
                    "spec": "compose",
                    "attempt": attempt,
                    "claims": 0,
                    "by_kind": {},
                    "report_path": True,
                    **summary,
                },
            )
            return text
        await self.ledger.log(
            "code_worker_unsubmitted",
            root_id,
            {"reason": reason, "spec": "compose", "attempt": attempt},
        )
        return None


async def reduce_and_resolve(
    synthesizer, ledger, source_tiers, root_id: str
) -> tuple[dict[str, NodeSummary], list[str]]:
    """Hierarchical reduce (AC-a) followed by per-node conflict resolution
    (AC-b, §6.7). Returns the (possibly annotated) summaries plus the
    deduplicated list of question ids whose high-value conflicts warrant
    reinvestigation."""
    summaries = await synthesizer.reduce_tree(root_id)
    reinvestigate: list[str] = []
    for qid, summary in list(summaries.items()):
        resolved, needs = await resolve_conflicts(ledger, summary, source_tiers)
        summaries[qid] = resolved
        for candidate in needs:
            if candidate not in reinvestigate:
                reinvestigate.append(candidate)
    return summaries, reinvestigate


async def collect_caveats(ledger, summaries: dict[str, NodeSummary]) -> list[str]:
    """Caveats surfaced in the final report (§6.8): unverified claims /
    dead ends per reduced node, abandoned questions, plus each node
    summary's own caveats (which include tier-difference footnotes from
    conflict resolution). Ledger accessors are read defensively so minimal
    test doubles don't need to implement them."""
    caveats: list[str] = []
    unverified_fn = getattr(ledger, "unverified_and_deadends", None)
    if unverified_fn is not None:
        for qid in summaries:
            for entry in await unverified_fn(qid):
                caveats.append(f"미확인: {entry}")
    questions_fn = getattr(ledger, "questions", None)
    if questions_fn is not None:
        for question in await questions_fn():
            if getattr(question, "status", None) == "abandoned":
                caveats.append(f"미조사: {question.text}")
    for summary in summaries.values():
        caveats.extend(summary.caveats)
    return _reader_facing_caveats(caveats)
