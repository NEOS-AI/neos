"""M1 sequential SCOUT orchestration loop."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace

from neos.config.model_routing import resolve_model
from neos.config.settings import settings

from .budgeter import Budgeter
from .citation import CitationRenderer, OrphanCitationError
from .conflict import resolve_conflicts
from .ledger import Ledger
from .llm import call_json
from .models import Assignment, Effort, NodeSummary, Verdict, WorkerResult
from .prompt_loader import render
from .synthesizer import Synthesizer
from .token_budget import (
    TokenBudget,
    TokenBudgetExhausted,
    token_budget_scope,
)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _wall_clock_cap(effort: Effort) -> float:
    return float(settings.config.deep_analysis.effort[effort.value].wall_clock_cap)


_REPAIR_PRESCRIPTIONS = {
    "E_OVERCLAIM": "문구를 증거 수준으로 약화(action=weakened, 재조사 금지)",
    "E_CONTRADICTED": "부정형으로 재작성(action=fixed, new_text=부정형)",
    "E_UNSUPPORTED": "다른 증거 탐색, 실패 시 action=abandoned",
    "E_QUOTE_MISMATCH": "salvage 출처에서 정확 발췌 재수집",
}


class SystemicWorkerFailure(RuntimeError):
    """Every assigned worker failed for too many consecutive rounds."""


_LIMITS_HEADING = "## 한계와 미확인 사항"
# Harness-owned, like `_LIMITS_HEADING` and CitationRenderer's `## 출처`.
# `graders/report.py` mirrors this string in its scoring boundaries.
# 한 패스가 트리를 무한정 넓히지 못하게 하는 상한. `_do_split` 이 자식을
# 4개로 자르는 것과 같은 수이며, 같은 이유다 -- 넓이는 예산을 나누고
# 예산이 갈리면 어느 가지도 답에 닿지 못한다.
_ADOPT_CAP = 4


def _normalize_question(text: str) -> str:
    """중복 판정용 정규화 -- 공백 접기 + 소문자 + 끝 문장부호 제거.

    완전한 의미 중복 제거가 아니다(원 설계 §6.3.2 는 그것을 LLM 심사자에게
    맡긴다). 같은 질문을 글자만 다르게 다시 조사하는 것을 막는 값싼 하한이다.
    """

    return " ".join(text.split()).strip(" ?？.。").lower()


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
    "empty_assembly": (
        "본문 조립이 비어 있어 결정론적 템플릿으로 대체되었습니다."
    ),
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


def _ensure_question_coverage(
    report: str, child_summaries: list[NodeSummary]
) -> str:
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


class Orchestrator:
    def __init__(
        self,
        session,
        run_id: str,
        worker_factory,
        grader,
        *,
        agentic_grader=None,
        ledger=None,
        decompose_fn=None,
        synthesizer=None,
        citation_renderer=None,
        report_grader=None,
        event_sink=None,
        checkpoint=None,
        llm_client=None,
        cassette=None,
        global_token_cap: int | None = None,
        finalization_floor_tokens: int = 0,
        report_floor_tokens: int = 0,
        grading_floor_tokens: int = 0,
        min_viable_output_tokens: int = 1,
        parallel_workers: int | None = None,
        max_depth: int | None = None,
        max_stall_rounds: int | None = None,
        synthesis_max_tokens: int | None = None,
    ) -> None:
        self.db = session
        self.run_id = run_id
        self.ledger = ledger or Ledger(session, run_id)
        self.worker_factory = worker_factory
        self.grader = grader
        self.agentic_grader = agentic_grader
        self.decompose_fn = decompose_fn or self._decompose
        self.synthesizer = synthesizer or Synthesizer(
            self.ledger,
            llm_client=llm_client,
            cassette=cassette,
            synthesis_max_tokens=synthesis_max_tokens,
        )
        self.citation_renderer = citation_renderer or CitationRenderer(
            self.ledger
        )
        self.report_grader = report_grader
        self.event_sink = event_sink
        self.checkpoint = checkpoint
        self.llm_client = llm_client
        self.cassette = cassette
        self.global_token_cap = (
            settings.DEEP_ANALYSIS_GLOBAL_TOKEN_CAP
            if global_token_cap is None
            else global_token_cap
        )
        # Injected, never computed here: integration and golden tests build
        # this orchestrator with caps as small as 1000, and a floor derived
        # from global config would leave those runs no investigation budget
        # at all. service.py computes it from the resolved profile.
        self.finalization_floor_tokens = finalization_floor_tokens
        # The inner tier, injected for the same reason as the floor above.
        # Golden tests build this with caps as small as 1,000; a tier derived
        # from global config would leave them no reduction budget at all.
        self.report_floor_tokens = report_floor_tokens
        self.grading_floor_tokens = grading_floor_tokens
        # Injected for the same reason as the floor above: a golden test with
        # a 1,000-token cap would have every reservation refused by the
        # shipped 2,048 default. Defaults to 1 -- the pre-2026-08-04
        # behaviour -- so only service.py opts real runs in.
        self.min_viable_output_tokens = min_viable_output_tokens
        config = settings.config.deep_analysis
        self.parallel_workers = (
            config.parallel_workers if parallel_workers is None else parallel_workers
        )
        self.max_depth = config.max_depth if max_depth is None else max_depth
        self.max_stall_rounds = (
            config.max_stall_rounds
            if max_stall_rounds is None
            else max_stall_rounds
        )
        # D15: per-question consecutive no-progress counter (in-memory, run
        # scoped). Reset on any progress; at the cap the question is force
        # terminated (SPLIT if depth allows, else abandon) to break the
        # zero-token-partial and always-mismatch livelock classes.
        self._stall_counts: dict[str, int] = {}
        # M4 §6.7: global conflict-reinvestigation counter (run scoped). At
        # most `conflict_reinvestigation_cap` extra investigation rounds may be
        # spent resolving equal-tier conflicts before the report is assembled
        # with both-sides annotations only.
        self._reinvestigation_count = 0
        # Run-scoped circuit breaker for systemic failures. Question-level
        # fail_streak already drives SPLIT; counting all-failed rounds here
        # prevents a shared dependency outage from expanding that tree.
        self._all_failed_rounds = 0
        self._token_budget_exhausted_logged = False
        self._investigation_stopped_at_floor_logged = False
        self._investigation_stopped_at_input_bound_logged = False
        self.token_budget = TokenBudget(
            self.global_token_cap,
            floor_tokens=self.finalization_floor_tokens,
            report_floor_tokens=self.report_floor_tokens,
            grading_floor_tokens=self.grading_floor_tokens,
            min_viable_output_tokens=self.min_viable_output_tokens,
        )
        self.budgeter = Budgeter(
            global_token_cap=self.global_token_cap,
            max_depth=self.max_depth,
            parallel_workers=self.parallel_workers,
            token_budget=self.token_budget,
        )
        self._split_decompose = self._default_split_decompose

    async def _emit(self, kind: str, payload: dict) -> None:
        if self.event_sink is not None:
            await _maybe_await(self.event_sink(kind, payload))

    async def _checkpoint(self) -> None:
        if self.checkpoint is not None:
            await _maybe_await(self.checkpoint())

    async def _persist_token_budget(
        self,
        kind: str,
        payload: dict,
    ) -> None:
        await self.ledger.log(kind, None, payload)
        await self._checkpoint()

    async def _install_token_budget(self) -> None:
        state_fn = getattr(self.ledger, "token_budget_state", None)
        if state_fn is None:
            consumed, outstanding = 0, {}
        else:
            consumed, outstanding = await state_fn()
        self.token_budget = TokenBudget(
            self.global_token_cap,
            consumed_tokens=consumed,
            outstanding=outstanding,
            persist=self._persist_token_budget,
            floor_tokens=self.finalization_floor_tokens,
            report_floor_tokens=self.report_floor_tokens,
            grading_floor_tokens=self.grading_floor_tokens,
            min_viable_output_tokens=self.min_viable_output_tokens,
        )
        self.budgeter.token_budget = self.token_budget

    async def _mark_token_budget_exhausted(self) -> None:
        if self._token_budget_exhausted_logged:
            return
        has_event = getattr(self.ledger, "has_event", None)
        if has_event is not None and await has_event("token_budget_exhausted"):
            self._token_budget_exhausted_logged = True
            return
        payload = {
            "cap_tokens": self.token_budget.cap_tokens,
            "consumed_tokens": self.token_budget.consumed_tokens,
            "reserved_tokens": self.token_budget.reserved_tokens,
        }
        await self.ledger.log("token_budget_exhausted", None, payload)
        await self._checkpoint()
        await self._emit("token_budget_exhausted", payload)
        self._token_budget_exhausted_logged = True

    async def _mark_investigation_stopped_at_floor(self) -> None:
        """Record that the investigation loop stopped because only the
        finalization floor remained -- not because the cap was exhausted.

        Before the floor existed, every run spent the cap to ~97% and
        `token_budget_exhausted` was the only signal available. Now
        `should_stop` (budgeter.py) halts earlier, at the floor, so that
        event stops firing for a reason unrelated to any real improvement --
        and without a replacement, a run that stopped clean at the floor is
        indistinguishable from one where investigation simply ran out of
        open questions. Payload carries counts only, mirroring
        `token_budget_exhausted` -- never report or response text.
        """
        if self._investigation_stopped_at_floor_logged:
            return
        has_event = getattr(self.ledger, "has_event", None)
        if has_event is not None and await has_event(
            "investigation_stopped_at_floor"
        ):
            self._investigation_stopped_at_floor_logged = True
            return
        payload = {
            "cap_tokens": self.token_budget.cap_tokens,
            "consumed_tokens": self.token_budget.consumed_tokens,
            "reserved_tokens": self.token_budget.reserved_tokens,
            "floor_tokens": self.token_budget.floor_tokens,
            "report_floor_tokens": self.token_budget.report_floor_tokens,
            "grading_floor_tokens": self.token_budget.grading_floor_tokens,
        }
        await self.ledger.log("investigation_stopped_at_floor", None, payload)
        await self._checkpoint()
        await self._emit("investigation_stopped_at_floor", payload)
        self._investigation_stopped_at_floor_logged = True

    async def _mark_investigation_stopped_at_input_bound(
        self, exc: TokenBudgetExhausted
    ) -> None:
        """Record that investigation stopped because a prompt would not fit
        the headroom left -- not because there was no headroom.

        `TokenBudget.reserve` refuses when `ceiling - input_bound` falls
        under viability even with `ceiling > 0`. Afterwards the budget looks
        like a run that simply had questions left, so neither state branch in
        `_mark_stop_reason` catches it and the stop went unrecorded (G10).
        Only the refusal carries the fact; this payload is what it carried.

        `floor_tokens` is deliberately absent. This stop did not reach the
        floor, and quoting floor numbers would read as if it had -- the same
        mistake, one label covering two facts, that G9 removed. `stage`,
        `input_bound` and `ceiling` say what failed to fit into what.

        Payload carries counts and identifiers only, mirroring the other two
        stop events -- never prompt or report text.
        """
        if self._investigation_stopped_at_input_bound_logged:
            return
        has_event = getattr(self.ledger, "has_event", None)
        if has_event is not None and await has_event(
            "investigation_stopped_at_input_bound"
        ):
            self._investigation_stopped_at_input_bound_logged = True
            return
        payload = {
            "cap_tokens": self.token_budget.cap_tokens,
            "consumed_tokens": self.token_budget.consumed_tokens,
            "reserved_tokens": self.token_budget.reserved_tokens,
            "stage": exc.stage,
            "model": exc.model,
            "input_bound": exc.input_bound,
            "ceiling": exc.ceiling,
        }
        await self.ledger.log(
            "investigation_stopped_at_input_bound", None, payload
        )
        await self._checkpoint()
        await self._emit("investigation_stopped_at_input_bound", payload)
        self._investigation_stopped_at_input_bound_logged = True

    async def _mark_stop_reason(
        self, exc: TokenBudgetExhausted | None = None
    ) -> None:
        """Record why investigation stopped, from the budget's state.

        The exception path used to assert "exhausted" on its own, and the
        normal path made a different decision from the same facts a few
        lines later -- two judgements of one question, disagreeing. Measured
        2026-08-04: 4 of 6 recorded stops were labelled `token_budget_
        exhausted` when the run had actually stopped at the floor with
        headroom left in the cap.

        `TokenBudget.reserve` raises the same `TokenBudgetExhausted` for
        every cause, so the exception *type* carries no information about
        which one happened. The budget's state answers two of the three;
        for the third only the exception's `cause` does, which is why it is
        now carried (token_budget.py).

        The floor branch below tests `<` against `min_viable_output_tokens`
        rather than `<= 0`, mirroring `Budgeter.should_stop`'s own viability
        threshold -- `<= 0` would leave the ordinary floor stop unrecorded,
        since the loop already halts once headroom drops below viability,
        not once it reaches zero.

        Order matters. The two state branches come first so G9's judgement
        is untouched: when the budget really is spent, the last refusal
        happening to carry a large prompt is not the reason the run stopped.
        The third branch only fills the silence -- a refusal raised while
        `available_for_investigation` still cleared viability, which used to
        satisfy no branch at all (G10).

        There is still deliberately no branch for a run that stopped because
        no open question cleared `score_floor`: it has no budget event to
        record, and inventing one would put the ledger back to guessing.

        All three `_mark_*` helpers are idempotent (in-memory flag plus a
        `has_event` lookup), so calling this from both paths cannot
        double-log.
        """
        if self.token_budget.exhausted:
            await self._mark_token_budget_exhausted()
        elif (
            self.token_budget.available_for_investigation
            < self.token_budget.min_viable_output_tokens
        ):
            await self._mark_investigation_stopped_at_floor()
        elif exc is not None and exc.cause == "input_bound":
            await self._mark_investigation_stopped_at_input_bound(exc)

    async def _grade(self, claim, value_est):
        """Two-stage grading: deterministic tier first; only claims that pass
        it (and only when an agentic grader is configured) proceed to the
        agentic semantic tier. A deterministic failure short-circuits so the
        expensive judge is never invoked on already-rejected claims."""
        verdict = await self.grader.grade(claim)  # deterministic first
        if self.agentic_grader is None:
            return replace(
                verdict,
                diagnostics={
                    **verdict.diagnostics,
                    "agentic": "not_configured",
                    "agentic_label": None,
                },
            )
        if not verdict.ok:
            return replace(
                verdict,
                diagnostics={
                    **verdict.diagnostics,
                    "agentic": "skipped",
                    "agentic_label": None,
                },
            )
        try:
            agentic_verdict = await self.agentic_grader.grade(claim, value_est)
            agentic_state = agentic_verdict.diagnostics.get(
                "agentic",
                (
                    "attempted_passed"
                    if agentic_verdict.ok
                    else "attempted_rejected"
                ),
            )
            return replace(
                agentic_verdict,
                diagnostics={
                    **verdict.diagnostics,
                    **agentic_verdict.diagnostics,
                    "agentic": agentic_state,
                    "agentic_label": agentic_verdict.label,
                },
            )
        except TokenBudgetExhausted:
            return replace(
                verdict,
                diagnostics={
                    **verdict.diagnostics,
                    "agentic": "exhausted",
                    "agentic_label": None,
                },
            )

    async def _regrade_pending(self, question_id, value_est):
        """Re-grade claims that repair processing pushed back to `pending`
        (weakened/negated forms) so a successful repair converges to verified
        immediately, and a still-failing one accrues toward the retry cap."""
        from .models import ProposedClaim, ProposedEvidence

        for claim, evidence in await self.ledger.pending_claims(question_id):
            proposed = ProposedClaim(
                text=claim.text,
                confidence=claim.confidence,
                evidence=[
                    ProposedEvidence(e.source_url, e.excerpt, e.raw_ref)
                    for e in evidence
                ],
            )
            verdict = await self._grade(proposed, value_est)
            await self.ledger.regrade_claim(question_id, claim.id, verdict)

    async def _run_worker(self, assignment: Assignment) -> WorkerResult:
        worker = self.worker_factory()  # A1: fresh instance per assignment
        try:
            return await asyncio.wait_for(
                worker.investigate(
                    assignment.brief,
                    assignment.effort,
                    assignment.question_id,
                    repairs=assignment.repairs,
                    question_text=assignment.question_text,
                ),
                timeout=_wall_clock_cap(assignment.effort),
            )
        except asyncio.TimeoutError:
            partial = worker.flush_partial(assignment.question_id)
            partial.status = "partial"
            return partial
        except Exception as exc:  # noqa: BLE001 - A1: any other failure -> failed
            return WorkerResult(
                question_id=assignment.question_id,
                status="failed",
                fail_reason=str(exc),
            )

    async def _decompose(self, root_text: str) -> list[dict]:
        config = settings.config.deep_analysis
        dig_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.dig,
        ).model
        prompt = render(
            "decompose",
            question_text=root_text,
            prior_findings="(없음)",
            dead_ends="(없음)",
        )
        data, _response = await call_json(
            dig_model,
            prompt,
            max_tokens=config.decompose_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
            stage="decompose",
        )
        return list(data.get("subquestions", []))[:7]

    async def _default_split_decompose(self, text, verified_summaries, dead_ends):
        config = settings.config.deep_analysis
        dig_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.dig,
        ).model
        prompt = render(
            "decompose",
            question_text=text,
            prior_findings=verified_summaries,
            dead_ends="\n".join(dead_ends) if dead_ends else "(없음)",
        )
        data, _response = await call_json(
            dig_model,
            prompt,
            max_tokens=config.decompose_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
            stage="split_decompose",
        )
        return list(data.get("subquestions", []))[:4]

    async def _ensure_root(self, root_text: str) -> str:
        existing = await self.ledger.root_question()
        if existing is not None:
            return existing.id

        root_id = await self.ledger.open_question(
            root_text,
            None,
            value_est=1.0,
            cap_tokens=self.global_token_cap,
            depth=0,
        )
        await self._emit(
            "question_opened",
            {"qid": root_id, "text": root_text, "depth": 0},
        )

        subquestions = await _maybe_await(self.decompose_fn(root_text))
        child_ids: list[str] = []
        child_cap = self.global_token_cap // max(1, len(subquestions))
        for subquestion in subquestions:
            child_id = await self.ledger.open_question(
                str(subquestion["text"]),
                root_id,
                value_est=float(subquestion.get("value_est", 0.5)),
                cap_tokens=child_cap,
                depth=1,
            )
            child_ids.append(child_id)
            await self._emit(
                "question_opened",
                {
                    "qid": child_id,
                    "text": str(subquestion["text"]),
                    "depth": 1,
                },
            )

        if child_ids:
            await self.ledger.record_split(root_id, child_ids)
            await self._emit(
                "split",
                {"qid": root_id, "children": child_ids},
            )
        await self._checkpoint()
        return root_id

    async def _partition(self, picks):
        assignments: list[Assignment] = []
        splits = []
        config = settings.config.deep_analysis
        for question, effort in picks:
            if effort == Effort.SPLIT:
                splits.append(question)
                continue
            feedback = await self.ledger.pending_feedback(question.id)
            repairs = [
                {
                    "claim_id": item.claim_id,
                    "code": item.code,
                    "detail": item.detail,
                    "salvage": item.salvage,
                }
                for item in feedback
            ]
            if repairs:
                repair_count = len(repairs)
                repairs_rendered = "\n".join(
                    f"{r['claim_id']} | {r['code']} | {r['detail']} | "
                    f"{_REPAIR_PRESCRIPTIONS.get(r['code'], '')} | "
                    f"{r['salvage'] or ''}"
                    for r in repairs
                )
            else:
                repair_count = 0
                repairs_rendered = "(없음)"
            # worker_brief.md [3] "확정된 발견 — 재조사 금지": 이 질문의 이전
            # 패스가 이미 확정한 클레임과 막다른 길을 워커에 전달해야 재조사가
            # 같은 길을 반복하지 않고 수렴한다. (첫 패스에는 둘 다 "(없음)".)
            # Ledger 접근자는 방어적으로 읽어 최소 test double은 구현할
            # 필요가 없게 한다(_collect_caveats와 동일한 패턴).
            summaries_fn = getattr(self.ledger, "verified_summaries", None)
            verified_summaries = (
                await summaries_fn(question.id)
                if summaries_fn is not None
                else "(없음)"
            )
            deadends_fn = getattr(
                self.ledger, "unverified_and_deadends", None
            )
            dead_end_entries = (
                await deadends_fn(question.id)
                if deadends_fn is not None
                else []
            )
            dead_ends_rendered = (
                "\n".join(f"- {entry}" for entry in dead_end_entries)
                if dead_end_entries
                else "(없음)"
            )
            brief = render(
                "worker_brief",
                question_text=question.text,
                verified_summaries=verified_summaries,
                dead_ends=dead_ends_rendered,
                repair_count=repair_count,
                repairs=repairs_rendered,
                token_cap=config.effort[effort.value].token_cap,
                confidence_cap_one=config.confidence_cap[1],
                confidence_cap_two=config.confidence_cap[2],
                confidence_cap_three_plus=config.confidence_cap[3],
                subq_adopt_threshold=config.subq_adopt_threshold,
            )
            assignments.append(
                Assignment(
                    question.id,
                    brief,
                    effort,
                    repairs,
                    question_text=question.text,
                )
            )
        return assignments, splits

    async def _adopt_subquestions(
        self, question_id: str, proposals: list
    ) -> None:
        """워커가 제안한 하위 질문 중 값이 되는 것을 트리에 넣는다 (D65).

        여태 이 자리는 로깅만 했다(D11 -> D13 이 두 번 연기). 표본 #16 에서
        **고유 제안 161건이 버려지고 실제 조사된 질문은 82건**이었고, 버려진
        것들이 판정자가 빠졌다고 지적한 바로 그 축이었다 -- `ca8fd65c` 는
        "PostgreSQL 코어 전문검색 … 을 다루지 않은 채" 로 반려됐는데 같은
        표본이 "PostgreSQL 17 공식 문서(Chapter 12. Full Text Search)" 를
        제안해 두고 버렸다.

        정책:

        - **임계값** `subq_adopt_threshold` -- config 에 정의만 되어 있고
          코드 어디에서도 쓰이지 않던 죽은 노브다. 이제 이것이 쓰인다.
        - **상한** `_ADOPT_CAP` -- 한 패스가 트리를 무한정 넓히지 못한다.
          `_do_split` 이 자식을 4개로 자르는 것과 같은 수다.
        - **중복 제거** -- 정규화한 텍스트가 이 run 의 기존 질문과 같으면
          버린다. 원 설계 §6.3.2 는 이것을 독립 LLM 심사자에게 맡기지만,
          그 심사자가 D11·D13 연기의 이유였다. 결정론적 일치는 완전하지
          않아도 공짜이고, 재탕을 다시 조사하는 것만은 막는다.
        - **깊이** -- `max_depth` 를 넘기지 않는다.
        - **예산** -- 부모의 잔여를 자식들과 부모가 나눈다(`n + 1`).
          `_do_split` 은 부모가 끝나므로 `n` 으로 나누지만, 채택된 부모는
          계속 조사하므로 자기 몫을 남겨야 한다.

        `record_split` 을 부르지 않는 것이 중요하다 -- 그것은 부모를 `split`
        으로 전이시켜 **부모의 조사를 끝낸다.** 채택은 부모가 살아 있는 채로
        가지를 더하는 일이다. `ledger.children()` 은 `parent_id` 로 조회하므로
        트리는 이것만으로 성립한다.
        """

        if not proposals:
            return
        config = settings.config.deep_analysis
        question = await self.ledger.get_question(question_id)
        if question is None or question.depth + 1 > self.max_depth:
            return

        existing = {
            _normalize_question(q.text) for q in await self.ledger.questions()
        }
        adopted: list = []
        for proposal in sorted(
            proposals, key=lambda p: p.value_est, reverse=True
        ):
            if len(adopted) >= _ADOPT_CAP:
                break
            if proposal.value_est < config.subq_adopt_threshold:
                continue
            key = _normalize_question(proposal.text)
            if key in existing:
                continue
            existing.add(key)
            adopted.append(proposal)

        if not adopted:
            return

        remaining = await self.ledger.remaining_budget(question_id)
        child_cap = max(1, remaining // (len(adopted) + 1))
        for proposal in adopted:
            child_id = await self.ledger.open_question(
                proposal.text,
                question_id,
                value_est=proposal.value_est,
                cap_tokens=child_cap,
                depth=question.depth + 1,
            )
            await self.ledger.log(
                "subq_adopted",
                child_id,
                {
                    "parent_id": question_id,
                    "value_est": proposal.value_est,
                    "depth": question.depth + 1,
                    "cap_tokens": child_cap,
                },
            )
            await self._emit(
                "question_opened",
                {
                    "qid": child_id,
                    "text": proposal.text,
                    "depth": question.depth + 1,
                },
            )

    async def _do_split(self, question) -> None:
        if question.depth >= self.max_depth:
            await self.ledger.record_abandon(question.id)
            await self._emit("abandoned", {"qid": question.id})
            return
        summaries = await self.ledger.verified_summaries(question.id)
        dead_ends = await self.ledger.unverified_and_deadends(question.id)
        children_specs = await _maybe_await(
            self._split_decompose(question.text, summaries, dead_ends)
        )
        children_specs = list(children_specs)[:4] or [
            {"text": question.text, "value_est": 0.5}
        ]
        remaining = await self.ledger.remaining_budget(question.id)
        config = settings.config.deep_analysis
        child_cap = max(1, remaining // max(1, len(children_specs)))
        child_ids: list[str] = []
        for spec in children_specs:
            child_id = await self.ledger.open_question(
                str(spec["text"]),
                question.id,
                value_est=question.value_est * config.value_decay,
                cap_tokens=child_cap,
                depth=question.depth + 1,
            )
            child_ids.append(child_id)
        await self.ledger.record_split(question.id, child_ids)
        await self._emit(
            "split",
            {"qid": question.id, "children": child_ids},
        )

    async def _verified_count(self, question_id: str) -> int | None:
        """Verified-claim count for the stall signal. Returns None when the
        (possibly faked) ledger does not expose `verified_claims`, which makes
        `_made_progress` treat the signal as changed and effectively disables
        the valve for minimal test doubles."""
        fn = getattr(self.ledger, "verified_claims", None)
        if fn is None:
            return None
        return len(await fn(question_id))

    async def _feedback_signal(self, question_id: str) -> int | None:
        fn = getattr(self.ledger, "feedback_count", None)
        if fn is None:
            return None
        return await fn(question_id)

    async def _made_progress(
        self,
        question_id: str,
        spent_before: int,
        verified_before: int | None,
        feedback_before: int | None,
    ) -> bool:
        """A pass made progress iff it produced a new verified claim, new
        rejection feedback, or burned tokens. An inert pass (partial with 0
        tokens/0 claims, or a mismatch-skipped assignment) fails all three.
        Unavailable signals (limited fakes) count as progress -> no stall."""
        question = await self.ledger.get_question(question_id)
        spent_after = (
            question.spent_tokens if question is not None else spent_before
        )
        if spent_after > spent_before:
            return True
        verified_after = await self._verified_count(question_id)
        if (
            verified_before is None
            or verified_after is None
            or verified_after > verified_before
        ):
            return True
        feedback_after = await self._feedback_signal(question_id)
        if (
            feedback_before is None
            or feedback_after is None
            or feedback_after > feedback_before
        ):
            return True
        return False

    async def _register_progress(
        self,
        question_id: str,
        made_progress: bool,
    ) -> None:
        """D15 stall safety valve: track consecutive no-progress passes and
        force-terminate at the cap so a livelocked question cannot spin to the
        global token cap."""
        if made_progress:
            self._stall_counts[question_id] = 0
            return
        count = self._stall_counts.get(question_id, 0) + 1
        self._stall_counts[question_id] = count
        if count >= self.max_stall_rounds:
            await self._force_terminate_stalled(question_id)

    async def _force_terminate_stalled(self, question_id: str) -> None:
        question = await self.ledger.get_question(question_id)
        if question is None or question.status != "open":
            return
        rounds = self._stall_counts.get(question_id, 0)
        await self.ledger.log(
            "stall_terminated",
            question_id,
            {"rounds": rounds},
        )
        await self._emit(
            "stall_terminated",
            {"qid": question_id, "rounds": rounds},
        )
        self._stall_counts[question_id] = 0
        # SPLIT if depth allows, else abandon (both handled by _do_split).
        await self._do_split(question)

    async def _register_round_outcome(
        self,
        results: list[WorkerResult],
    ) -> None:
        """Stop a run when every assigned worker repeatedly fails."""
        if not results:
            return
        if any(result.status != "failed" for result in results):
            self._all_failed_rounds = 0
            return
        self._all_failed_rounds += 1
        if self._all_failed_rounds < self.max_stall_rounds:
            return

        reasons = [
            (result.fail_reason or "unknown")[:200] for result in results
        ]
        payload = {
            "rounds": self._all_failed_rounds,
            "reasons": reasons,
        }
        await self.ledger.log(
            "systemic_failure_terminated",
            None,
            payload,
        )
        await self._emit("systemic_failure_terminated", payload)
        await self._checkpoint()
        raise SystemicWorkerFailure(
            "all workers failed for "
            f"{self._all_failed_rounds} consecutive rounds"
        )

    async def _run_round(self) -> bool:
        """Execute one SCOUT round: select → partition → split → workers →
        commit. Returns ``False`` when there is nothing to select (caller must
        stop), ``True`` otherwise. Factored out of ``run`` so ``_finalize``
        can drive a single bounded conflict-reinvestigation round through the
        exact same select/worker/commit path."""
        picks = await self.budgeter.select(self.ledger)
        if not picks:
            return False
        assignments, splits = await self._partition(picks)

        for question in splits:
            await self._do_split(question)
        await self._checkpoint()

        for assignment in assignments:
            await self.ledger._transition(
                assignment.question_id,
                "investigating",
            )
        results = await asyncio.gather(
            *[self._run_worker(a) for a in assignments]
        )
        await self._register_round_outcome(results)
        # P2: 순차 커밋 (single-writer). gather는 순서를 보존하므로
        # assignments[i] ↔ results[i]가 1:1 대응한다.
        for assignment, result in zip(assignments, results):
            question = await self.ledger.get_question(result.question_id)
            # question_id 가드(M2 이월): 워커가 투입한 것과 다른
            # question_id를 돌려주면(또는 존재하지 않는 질문이면) 커밋하지
            # 않고, 실제 투입 질문을 investigating→open으로 복귀시켜
            # 영구 investigating 잠김을 방지한다.
            if (
                question is None
                or result.question_id != assignment.question_id
            ):
                await self._emit(
                    "worker_result_mismatch",
                    {
                        "expected_qid": assignment.question_id,
                        "got_qid": result.question_id,
                    },
                )
                await self.ledger.log(
                    "worker_result_mismatch",
                    assignment.question_id,
                    {"got_qid": result.question_id},
                )
                await self.ledger._transition(
                    assignment.question_id,
                    "open",
                )
                # D15: a mismatch-skipped assignment made no progress.
                await self._register_progress(assignment.question_id, False)
                continue
            value_est = question.value_est
            # D15 progress snapshot (before this pass mutates state).
            spent_before = question.spent_tokens
            verified_before = await self._verified_count(
                assignment.question_id
            )
            feedback_before = await self._feedback_signal(
                assignment.question_id
            )
            await self.ledger.commit_blobs(result.blobs)
            # P2: the worker has no ledger, so it flags the skip on its result
            # and the single writer records it here -- the same shape the
            # discarded-claim loop below already uses.
            if result.entailment_skipped:
                await self.ledger.log(
                    "entailment_filter_skipped",
                    result.question_id,
                    {
                        "claim_count": len(result.claims),
                        "reason": "entailment_unavailable",
                    },
                )
            # Recall measurement: entailment drops claims before grading, so
            # they never reach the claims table. Record them here — blobs are
            # already committed above, so phase 2 can re-grade offline.
            for discarded in result.discarded_claims:
                await self.ledger.log(
                    "claim_discarded",
                    result.question_id,
                    {
                        "text": discarded.text,
                        "confidence": discarded.confidence,
                        "value_est": value_est,
                        "evidence": [
                            {
                                "source_url": evidence.source_url,
                                "excerpt": evidence.excerpt,
                                "raw_ref": evidence.raw_ref,
                            }
                            for evidence in discarded.evidence
                        ],
                    },
                )
            # verdicts는 claim 텍스트로 키잉한다. 이는 Ledger의 hash 기반
            # 병합(§6.1.3, D3)과 정합적이다 — 동일 텍스트 클레임은 커밋 시
            # 하나의 claim으로 병합되므로 텍스트당 verdict 하나가 맞다.
            verdicts = {}
            for claim in result.claims:
                verdicts[claim.text] = await self._grade(claim, value_est)
            await self.ledger.commit_pass(
                result.question_id,
                result,
                verdicts,
            )
            await self._regrade_pending(result.question_id, value_est)
            # D15: assess progress and trip the stall valve if this
            # question has made none for max_stall_rounds in a row.
            made_progress = await self._made_progress(
                assignment.question_id,
                spent_before,
                verified_before,
                feedback_before,
            )
            await self._register_progress(
                assignment.question_id, made_progress
            )
            for subq in result.proposed_subquestions:
                await self.ledger.log(
                    "subq_proposed",
                    result.question_id,
                    {"text": subq.text, "value_est": subq.value_est},
                )
            await self._adopt_subquestions(
                result.question_id, result.proposed_subquestions
            )
            await self._emit(
                "pass_completed",
                {
                    "qid": result.question_id,
                    "status": result.status,
                    "claims": len(result.claims),
                    "tokens": result.tokens_spent,
                },
            )
            # 패스가 끝날 때마다 커밋한다. Ledger.log()는 flush만 하므로
            # 커밋 전까지 이벤트는 다른 세션(SSE 소비자)에 보이지 않는다.
            # 라운드 끝에 한 번만 커밋하면 그 라운드의 진행이 뭉텅이로
            # 나타나고, 크래시 시 라운드 전체 작업이 날아간다.
            await self._checkpoint()
        await self._checkpoint()
        return True

    async def _reduce_and_resolve(
        self, root_id: str
    ) -> tuple[dict[str, NodeSummary], list[str]]:
        """Hierarchical reduce (AC-a) followed by per-node conflict resolution
        (AC-b, §6.7). Returns the (possibly annotated) summaries plus the
        deduplicated list of question ids whose high-value conflicts warrant
        reinvestigation."""
        config = settings.config.deep_analysis
        summaries = await self.synthesizer.reduce_tree(root_id)
        reinvestigate: list[str] = []
        for qid, summary in list(summaries.items()):
            resolved, needs = await resolve_conflicts(
                self.ledger, summary, config.source_tiers
            )
            summaries[qid] = resolved
            for candidate in needs:
                if candidate not in reinvestigate:
                    reinvestigate.append(candidate)
        return summaries, reinvestigate

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

    async def _collect_caveats(
        self, summaries: dict[str, NodeSummary]
    ) -> list[str]:
        """Caveats surfaced in the final report (§6.8): unverified claims /
        dead ends per reduced node, abandoned questions, plus each node
        summary's own caveats (which include tier-difference footnotes from
        conflict resolution). Ledger accessors are read defensively so minimal
        test doubles don't need to implement them."""
        caveats: list[str] = []
        unverified_fn = getattr(self.ledger, "unverified_and_deadends", None)
        if unverified_fn is not None:
            for qid in summaries:
                for entry in await unverified_fn(qid):
                    caveats.append(f"미확인: {entry}")
        questions_fn = getattr(self.ledger, "questions", None)
        if questions_fn is not None:
            for question in await questions_fn():
                if getattr(question, "status", None) == "abandoned":
                    caveats.append(f"미조사: {question.text}")
        for summary in summaries.values():
            caveats.extend(summary.caveats)
        return _reader_facing_caveats(caveats)

    async def _finalize(self, root_id: str) -> str:
        """Reduce the tree, resolve conflicts (with at most one bounded
        reinvestigation round), then assemble → render → grade the report with
        a bounded retry loop. Never exits empty-handed (§6.8): on cap
        exhaustion a failure appendix is attached to the last draft."""
        config = settings.config.deep_analysis
        summaries, reinvestigate = await self._reduce_and_resolve(root_id)
        await self._emit("synth_pass", {"qid": root_id})

        # M4 §6.7: at most ONE conflict-reinvestigation round per run. The gate
        # is the EVENT LOG (not the in-memory counter, which resets on
        # crash-recovery) so a resumed run cannot spend a second round. When it
        # fires we reopen the owning question through the §6.7-sanctioned
        # `reopen_for_reinvestigation` path -- the target is `resolved` at
        # finalize time, so a plain `_transition(..., "open")` would raise
        # IllegalTransition and (previously, swallowed) make the round a no-op.
        has_event_fn = getattr(self.ledger, "has_event", None)
        if has_event_fn is not None:
            already_reinvestigated = await has_event_fn(
                "conflict_reinvestigation"
            )
        else:
            # Minimal ledger doubles fall back to the in-memory counter.
            already_reinvestigated = (
                self._reinvestigation_count
                >= config.conflict_reinvestigation_cap
            )
        if reinvestigate and not already_reinvestigated:
            self._reinvestigation_count += 1
            target = reinvestigate[0]
            await self.ledger.log(
                "conflict_reinvestigation",
                target,
                {"qids": reinvestigate},
            )
            await self.ledger.reopen_for_reinvestigation(target)
            # This round runs real workers, so it can exhaust the budget --
            # and unlike the main investigation loop (`run`, which catches
            # exactly this) nothing here did. The exception escaped
            # `_finalize` to `run`'s generic handler, which fails the run:
            # `8817a935` in sample #8 died as
            # `job_failed(deep-analysis token budget exhausted)` with no
            # report at all, the first budget-caused hard failure among the
            # ledger's 15 job failures. §6.8 forbids the empty-handed exit;
            # a run that spent its budget still has summaries to assemble
            # from, and reinvestigation is an *optional* extra round.
            try:
                await self._run_round()
                summaries, reinvestigate = await self._reduce_and_resolve(
                    root_id
                )
            except TokenBudgetExhausted as exc:
                await self._mark_stop_reason(exc)

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
        caveats = await self._collect_caveats(summaries)
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
        # `last` remains the fallback for the case where every attempt
        # orphaned: there is no rendered text then, and a raw draft still
        # beats exiting empty-handed.
        chosen = _best_rejected_draft(rejected)
        report = (chosen or last_rendered or last or "") + (
            "\n\n## 부록: 미해결 사유\n조립/채점 재시도 캡 소진."
        )
        await self.ledger.complete_run()
        return report

    async def run(self, root_text: str) -> dict[str, str]:
        await self._install_token_budget()
        with token_budget_scope(self.token_budget):
            try:
                recovered = await self.ledger.recover()
                if recovered:
                    await self._emit("recovered", {"questions": recovered})
                    await self._checkpoint()

                try:
                    root_id = await self._ensure_root(root_text)

                    while not await self.budgeter.should_stop(self.ledger):
                        if not await self._run_round():
                            break
                except TokenBudgetExhausted as exc:
                    await self._mark_stop_reason(exc)
                    root = await self.ledger.root_question()
                    if root is None:
                        raise
                    root_id = root.id

                await self._mark_stop_reason()

                report = await self._finalize(root_id)
                await self._checkpoint()
                await self._emit(
                    "completed",
                    {
                        "run_id": self.run_id,
                        "token_cap": self.token_budget.cap_tokens,
                        "tokens_consumed": self.token_budget.consumed_tokens,
                        "tokens_reserved": self.token_budget.reserved_tokens,
                        "token_budget_exhausted": self.token_budget.exhausted,
                    },
                )
                return {
                    "report_markdown": report,
                    "run_id": self.run_id,
                }
            except Exception:
                rollback = getattr(self.db, "rollback", None)
                if rollback is not None:
                    await _maybe_await(rollback())
                await self.ledger.fail_run()
                await self._checkpoint()
                await self._emit(
                    "failed",
                    {
                        "run_id": self.run_id,
                        "token_cap": self.token_budget.cap_tokens,
                        "tokens_consumed": self.token_budget.consumed_tokens,
                        "tokens_reserved": self.token_budget.reserved_tokens,
                        "token_budget_exhausted": self.token_budget.exhausted,
                    },
                )
                raise
