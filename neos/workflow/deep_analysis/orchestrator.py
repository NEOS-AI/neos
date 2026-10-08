"""M1 sequential SCOUT orchestration loop."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace

from neos.config.settings import settings

from neos.coding.sandbox.base import SandboxLimits
from neos.subagent.types import StepKind

from .budgeter import Budgeter
from .citation import CitationRenderer
from .fetch import fetch_url
from .ledger import Ledger
from .llm import call_json
from .model_roles import resolve_harness_effort, resolve_harness_model
from .assignment import build_assignment
from .models import Assignment, Effort, WorkerResult
from .prompt_loader import render
from .research_session import CommandLimits
from .report_writer import ReportWriter, reduce_and_resolve
from .research_worker import run_research_worker
from .subagent_adapter import (
    investigate_via_subagent,
    latest_subagent_pointers,
    log_subagent_step,
)
from .stall import StallTracker, made_progress, snapshot
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


class SystemicWorkerFailure(RuntimeError):
    """Every assigned worker failed for too many consecutive rounds."""



def adopted_child_caps(remaining: int, values: list[float], policy: str) -> list[int]:
    """채택된 자식들에게 부모의 잔여 예산을 나눈다.

    두 정책 다 **부모 몫 하나를 먼저 뗀다.** `_do_split` 은 부모가 `split` 로
    끝나므로 `n` 으로 나누지만, 채택된 부모는 계속 조사하므로 `n + 1` 이다.

    - `uniform` -- 균등. D65 의 정책이고 표본 #17 이 이것으로 측정됐다.
    - `value_weighted` -- 나머지 `n` 몫을 `value_est` 비율로 나눈다. 표본 #17
      에서 질문이 2.1배가 되는 동안 `claim_verified` 는 129 -> 116 으로 줄었다.
      균등 분할이 넓이를 사면서 **자식마다의 깊이를 팔았다**는 가설의 손잡이다.

    값이 전부 0 이면(옛 형태의 문자열 제안은 `value_est=0.0` 이다) 비율을 만들
    수 없으므로 균등으로 떨어진다 -- 0 으로 나누지 않기 위해서가 아니라, 그
    경우 "값에 비례"가 아무 의미도 없기 때문이다.

    최소 1 을 보장한다. 0 토큰짜리 자식은 열리자마자 바닥에 걸린다.
    """

    count = len(values)
    if count == 0:
        return []
    share = max(0, remaining) // (count + 1)
    if policy != "value_weighted":
        return [max(1, share)] * count

    total = sum(max(0.0, v) for v in values)
    if total <= 0:
        return [max(1, share)] * count

    pool = share * count
    return [max(1, int(pool * max(0.0, v) / total)) for v in values]


def _apply_review(proposals: list, reviewed: list) -> list:
    """심사자의 응답을 제안 목록에 입힌다.

    심사자는 **인덱스로 말한다** -- 텍스트를 되받아 적게 하면 그것이 곧 재작성
    이고, 워커가 실제 증거에서 뽑은 문장이 심사 과정에서 조용히 바뀐다.
    인덱스는 그런 일이 일어날 수 없게 한다.

    응답에 없는 인덱스는 **버려진 것**이다(의미 중복 병합의 결과). 알 수 없는
    인덱스와 잘못된 값은 무시한다 -- 심사자의 실수가 제안을 없애면 안 된다.
    전부 무효면 원래 목록을 돌려준다.
    """

    kept: list = []
    seen: set[int] = set()
    for item in reviewed:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["index"])
            value = float(item["value_est"])
        except (KeyError, TypeError, ValueError):
            continue
        if index in seen or not 0 <= index < len(proposals):
            continue
        seen.add(index)
        kept.append(replace(proposals[index], value_est=min(1.0, max(0.0, value))))
    return kept or proposals


def _normalize_question(text: str) -> str:
    """중복 판정용 정규화 -- 공백 접기 + 소문자 + 끝 문장부호 제거.

    완전한 의미 중복 제거가 아니다(원 설계 §6.3.2 는 그것을 LLM 심사자에게
    맡긴다). 같은 질문을 글자만 다르게 다시 조사하는 것을 막는 값싼 하한이다.
    """

    return " ".join(text.split()).strip(" ?？.。").lower()



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
        subagent_runtime=None,
        # 트랙 J. 둘 다 `deep_analysis.code_research_enabled` 가 켜졌을 때만
        # 쓰인다. 꺼져 있으면 읽히지도 않는다 (I1).
        sandbox_provider=None,
        research_runtime_factory=None,
        compose_runtime_factory=None,
        stall_tracker: StallTracker | None = None,
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
        self.citation_renderer = citation_renderer or CitationRenderer(self.ledger)
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
            config.max_stall_rounds if max_stall_rounds is None else max_stall_rounds
        )
        # `self.stall.max_rounds` is the cap that counts (an injected tracker
        # brings its own); `max_stall_rounds` only seeds the default tracker.
        # D15: per-question consecutive no-progress counter and the run-scoped
        # all-failed-rounds breaker live in the tracker (in-memory). At the cap
        # the question is force terminated (SPLIT if depth allows, else
        # abandon) to break the zero-token-partial and always-mismatch
        # livelock classes; the tracker only decides, this class acts.
        self.stall = (
            stall_tracker
            if stall_tracker is not None
            else StallTracker(self.max_stall_rounds)
        )
        # M4 §6.7: global conflict-reinvestigation counter (run scoped). At
        # most `conflict_reinvestigation_cap` extra investigation rounds may be
        # spent resolving equal-tier conflicts before the report is assembled
        # with both-sides annotations only.
        self._reinvestigation_count = 0
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
        self.subagent_runtime = subagent_runtime
        self.sandbox_provider = sandbox_provider
        self.research_runtime_factory = research_runtime_factory
        # 트랙 J4 (D105). `compose` 스펙은 synth 모델로 돈다 -- research 런타임(dig)과 따로 짓는다.
        self.compose_runtime_factory = compose_runtime_factory
        self.report_writer = ReportWriter(
            self.ledger,
            self.synthesizer,
            self.citation_renderer,
            self.report_grader,
            sandbox_provider=self.sandbox_provider,
            compose_runtime_factory=self.compose_runtime_factory,
            checkpoint=self._checkpoint,
        )

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
        if has_event is not None and await has_event("investigation_stopped_at_floor"):
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
        await self.ledger.log("investigation_stopped_at_input_bound", None, payload)
        await self._checkpoint()
        await self._emit("investigation_stopped_at_input_bound", payload)
        self._investigation_stopped_at_input_bound_logged = True

    async def _mark_stop_reason(self, exc: TokenBudgetExhausted | None = None) -> None:
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

    async def _computed_judge_context(self, claim, question_id):
        """GRADE1: what the judge reads instead of excerpts for a computed claim.

        Only called after the deterministic tier passed, so every premise is
        a verified quote claim of this run.
        """
        from .graders.agentic import ComputedJudgeContext

        question = (
            await self.ledger.get_question(question_id) if question_id else None
        )
        premises = []
        for claim_id in claim.computation.premises:
            premise = await self.ledger.get_claim(claim_id)
            if premise is None:
                continue
            evidence = await self.ledger.claim_evidence(claim_id)
            premises.append(
                (premise.text, tuple(item.excerpt for item in evidence))
            )
        return ComputedJudgeContext(
            question_text=question.text if question is not None else "",
            computed_value=claim.computation.claimed_value,
            premises=tuple(premises),
        )

    async def _grade(self, claim, value_est, question_id=None):
        """Two-stage grading: deterministic tier first; only claims that pass
        it (and only when an agentic grader is configured) proceed to the
        agentic semantic tier. A deterministic failure short-circuits so the
        expensive judge is never invoked on already-rejected claims."""
        # deterministic first. 계산 클레임만 질문을 넘긴다 -- 전제가 같은
        # 질문의 것인지 본다(계약 §9 결정 3). quote 경로의 호출은 그대로다.
        if getattr(claim, "kind", "quote") == "computed":
            verdict = await self.grader.grade(claim, question_id=question_id)
        else:
            verdict = await self.grader.grade(claim)
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
            if getattr(claim, "kind", "quote") == "computed":
                agentic_verdict = await self.agentic_grader.grade(
                    claim,
                    value_est,
                    computed=await self._computed_judge_context(claim, question_id),
                )
            else:
                agentic_verdict = await self.agentic_grader.grade(claim, value_est)
            agentic_state = agentic_verdict.diagnostics.get(
                "agentic",
                ("attempted_passed" if agentic_verdict.ok else "attempted_rejected"),
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
        except TokenBudgetExhausted as exc:
            # C3-m1: `reserve()` refuses *before* dispatch, so the attempt
            # that raised spent nothing -- but `call_json` stamps `exc.
            # tokens_spent` with what earlier attempts in the *same* judge
            # call already burned (llm.py's `_charge`). Those tokens were
            # really sent to the provider and are already deducted from the
            # global `TokenBudget`; the only thing missing is attributing
            # them to this question. Dropping them here (as the old code
            # did, via the deterministic `verdict` whose `tokens_spent` is
            # always 0) would silently write off real spend, which is
            # exactly the bug this task closes -- so they are carried
            # forward instead. `judge_tokens` mirrors `tokens_spent` in the
            # diagnostics, same as every other branch in
            # `AgenticGrader._diagnostics`, so the two never diverge.
            return replace(
                verdict,
                diagnostics={
                    **verdict.diagnostics,
                    "agentic": "exhausted",
                    "agentic_label": None,
                    "judge_tokens": exc.tokens_spent,
                },
                tokens_spent=exc.tokens_spent,
            )

    async def _regrade_pending(self, question_id, value_est):
        """Re-grade claims that repair processing pushed back to `pending`
        (weakened/negated forms) so a successful repair converges to verified
        immediately, and a still-failing one accrues toward the retry cap."""
        from .ledger import stored_computation
        from .models import ProposedClaim, ProposedEvidence

        for claim, evidence in await self.ledger.pending_claims(question_id):
            # `kind` and `computation` come back with the row. Without them a
            # repaired computed claim was regraded as a quote with no excerpts
            # and could only fail E_NO_EVIDENCE (GRADE1 follow-up).
            kind = getattr(claim, "kind", None) or "quote"
            proposed = ProposedClaim(
                text=claim.text,
                confidence=claim.confidence,
                evidence=[
                    ProposedEvidence(e.source_url, e.excerpt, e.raw_ref)
                    for e in evidence
                ],
                kind=kind,
                computation=(
                    stored_computation(getattr(claim, "computation", None))
                    if kind == "computed"
                    else None
                ),
            )
            verdict = await self._grade(proposed, value_est, question_id)
            await self.ledger.regrade_claim(question_id, claim.id, verdict)

    async def _run_worker(
        self,
        assignment: Assignment,
        *,
        child_run_id: str | None = None,
        child_checkpoint_id: str | None = None,
    ) -> WorkerResult:
        if settings.config.deep_analysis.code_research_enabled:
            # 조용한 degrade 금지 (계약 §3.4 와 같은 방향): 켜 두었는데 조각이
            # 빠졌으면 옛 경로로 슬쩍 떨어지지 않는다. 그러면 "조사 모드로
            # 돌고 있다" 고 믿는 실행이 사실은 옛 워커를 돌리고, 원장에는 그
            # 사실이 남지 않는다. 두 사유를 **따로** 적는 이유는 설정을 고칠
            # 때 어느 쪽이 빠졌는지 보이게 하기 위해서다.
            if self.sandbox_provider is None:
                return WorkerResult(
                    question_id=assignment.question_id,
                    status="failed",
                    fail_reason="sandbox_provider_missing",
                )
            if self.research_runtime_factory is None:
                return WorkerResult(
                    question_id=assignment.question_id,
                    status="failed",
                    fail_reason="research_runtime_factory_missing",
                )
            research = settings.config.deep_analysis.code_research
            await self.ledger.log(
                "code_worker_started",
                assignment.question_id,
                {
                    "spec": "research",
                    "profile": research.sandbox_profile,
                    # 재개면 이어받는 자식, 처음이면 빈 문자열.
                    "run_id": child_run_id or "",
                },
            )
            result = await run_research_worker(
                assignment,
                ledger=self.ledger,
                provider=self.sandbox_provider,
                grader=self.grader,
                cap_bytes=research.evidence_bytes_cap,
                limits=SandboxLimits.safe_defaults(),
                fetch_fn=fetch_url,
                runtime_factory=self.research_runtime_factory,
                parent_id=str(self.ledger.run_id),
                run_id=child_run_id,
                expected_checkpoint_id=child_checkpoint_id,
                # 원장의 `code_worker_started.profile` 과 **같은 값**이다. 적은
                # 이름과 실제로 연 이름이 갈라지면 원장이 거짓말을 한다.
                profile=research.sandbox_profile,
                # 재실행과 **같은 한도**다. 워커 안에서 끝난 계산이 채점 때
                # 한도에 걸리지 않게 한다.
                command_limits=CommandLimits(
                    timeout_sec=research.reexecution.cpu_sec,
                    output_bytes=research.reexecution.stdout_bytes,
                ),
            )
            await self._log_code_worker_outcome(assignment.question_id, result)
            return result
        if settings.config.deep_analysis.subagent_enabled:
            if self.subagent_runtime is None:
                return WorkerResult(
                    question_id=assignment.question_id,
                    status="failed",
                    fail_reason="subagent_runtime_missing",
                )
            return await investigate_via_subagent(
                runtime=self.subagent_runtime,
                assignment=assignment,
                parent_id=str(self.ledger.run_id),
                run_id=child_run_id,
                expected_checkpoint_id=child_checkpoint_id,
            )
        return await self._run_legacy_worker(assignment)

    async def _log_code_worker_outcome(
        self, question_id: str, result: WorkerResult
    ) -> None:
        """제출됐는가, 아니면 왜 아닌가 (계약 §6).

        **아직 끝나지 않은 턴은 둘 중 어느 것도 아니다.** `continuing` 을
        미제출로 적으면 다음 라운드가 이어받을 작업이 원장에서는 실패한
        것처럼 보인다.
        """
        if result.subagent_step_kind == StepKind.CONTINUING.value:
            return
        if result.fail_reason:
            await self.ledger.log(
                "code_worker_unsubmitted",
                question_id,
                {"reason": result.fail_reason},
            )
            return
        by_kind: dict[str, int] = {}
        for claim in result.claims:
            by_kind[claim.kind] = by_kind.get(claim.kind, 0) + 1
        await self.ledger.log(
            "code_worker_submitted",
            question_id,
            {
                "claims": len(result.claims),
                "by_kind": by_kind,
                "report_path": result.report_path is not None,
            },
        )

    async def _run_legacy_worker(self, assignment: Assignment) -> WorkerResult:
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
            # C3: a bare result reports 0 tokens, but the worker may have run
            # several billed calls before the one that raised. The timeout
            # branch above never had this problem -- `flush_partial` reads the
            # same counter -- so the loss was confined to this branch and to
            # the failure modes it catches, which is why it stayed invisible.
            return WorkerResult(
                question_id=assignment.question_id,
                status="failed",
                fail_reason=str(exc),
                tokens_spent=worker.tokens_spent,
                model=worker.model,
            )

    async def _decompose(self, root_text: str) -> list[dict]:
        config = settings.config.deep_analysis
        dig_model = resolve_harness_model("dig").model
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
            effort=resolve_harness_effort("dig").effort,
        )
        return list(data.get("subquestions", []))[:7]

    async def _default_split_decompose(self, text, verified_summaries, dead_ends):
        config = settings.config.deep_analysis
        dig_model = resolve_harness_model("dig").model
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
            effort=resolve_harness_effort("dig").effort,
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
        """지시 조립은 `assignment.py` 에 있다 -- J3 섀도가 같은 brief 를
        지어야 하고, 두 벌이면 한쪽만 고쳐지는 날이 온다."""
        assignments: list[Assignment] = []
        splits = []
        for question, effort in picks:
            if effort == Effort.SPLIT:
                splits.append(question)
                continue
            assignments.append(
                await build_assignment(self.ledger, question, effort)
            )
        return assignments, splits

    async def _review_subquestions(self, question, proposals: list) -> list:
        """§6.3.2 의 독립 심사자 -- 제안들의 **상대 가치**를 다시 매긴다.

        D11 -> D13 -> D65 가 세 번 미룬 자리다. D65 는 워커가 자기 제안에 스스로
        값을 매기게 했다. 공짜지만 공정하지 않고, 표본 #17 이 그 대가를 보여줬을
        수 있다 -- 채택 88건에 `resolved` 2건, 새로 생긴 `abandoned` 15건.

        심사자가 워커와 다른 점은 **한 번에 전부 본다**는 것이다. 워커는 자기
        제안 하나하나에 절대값을 매기지만, 예산은 상대적으로 갈린다. 그리고
        `_normalize_question` 이 못 잡는 **의미 중복**(같은 것을 다른 말로)을
        여기서 병합한다.

        꺼져 있으면(기본) 제안을 그대로 돌려준다 -- 표본 하나는 변경 하나만
        재야 하므로 예산 정책과 이것을 동시에 켜지 않는다(§10.2).

        **실패는 삼킨다.** 심사자는 조사를 돕는 장치이지 관문이 아니다. 여기서
        터지면 워커가 실제로 수집한 증거에서 나온 제안이 통째로 사라지는데,
        그것이 D65 가 고친 바로 그 손실이다. 대신 `subq_review_failed` 를
        남긴다 -- 조용히 원래 값으로 돌아가면 심사자가 도는지 아닌지 알 수 없다.
        """

        config = settings.config.deep_analysis
        if not config.subq_reviewer_enabled or not proposals:
            return proposals

        try:
            judge_model = resolve_harness_model("judge").model
            prompt = render(
                "subq_review",
                question_text=question.text,
                proposals="\n".join(
                    f"{i}. [{p.value_est:.2f}] {p.text}"
                    for i, p in enumerate(proposals)
                ),
                subq_adopt_threshold=config.subq_adopt_threshold,
                resolve_threshold=config.resolve_threshold,
            )
            data, _response = await call_json(
                judge_model,
                prompt,
                max_tokens=config.subq_reviewer_max_output_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="subq_review",
                effort=resolve_harness_effort("judge").effort,
            )
            reviewed = _apply_review(proposals, data.get("reviewed", []))
        except Exception as error:  # noqa: BLE001 -- 위 독스트링
            await self.ledger.log(
                "subq_review_failed",
                question.id,
                {"error_type": type(error).__name__, "proposals": len(proposals)},
            )
            return proposals

        await self.ledger.log(
            "subq_reviewed",
            question.id,
            {
                "before": len(proposals),
                "after": len(reviewed),
                "value_before": round(
                    sum(p.value_est for p in proposals) / len(proposals), 3
                ),
                "value_after": (
                    round(sum(p.value_est for p in reviewed) / len(reviewed), 3)
                    if reviewed
                    else 0.0
                ),
            },
        )
        return reviewed

    async def _adopt_subquestions(self, question_id: str, proposals: list) -> None:
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
        - **상한** `subq_adopt_cap` -- 한 패스가 트리를 무한정 넓히지 못한다.
          D65 는 `_do_split` 과 같은 4 를 하드코딩했으나, 표본 #17 이 넓이의
          대가를 보여줬으므로(질문 2.1배, `claim_verified` 129 -> 116) 이제
          config 노브다.
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

        existing = {_normalize_question(q.text) for q in await self.ledger.questions()}
        proposals = await self._review_subquestions(question, proposals)
        cap = max(1, config.subq_adopt_cap)
        adopted: list = []
        for proposal in sorted(proposals, key=lambda p: p.value_est, reverse=True):
            if len(adopted) >= cap:
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
        caps = adopted_child_caps(
            remaining,
            [p.value_est for p in adopted],
            config.subq_budget_policy,
        )
        for proposal, child_cap in zip(adopted, caps):
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

    async def _register_progress(
        self,
        question_id: str,
        made_progress: bool,
    ) -> None:
        """D15 stall safety valve: track consecutive no-progress passes and
        force-terminate at the cap so a livelocked question cannot spin to the
        global token cap."""
        if self.stall.record(question_id, made_progress):
            await self._force_terminate_stalled(question_id)

    async def _force_terminate_stalled(self, question_id: str) -> None:
        question = await self.ledger.get_question(question_id)
        if question is None or question.status != "open":
            return
        rounds = self.stall.count(question_id)
        await self.ledger.log(
            "stall_terminated",
            question_id,
            {"rounds": rounds},
        )
        await self._emit(
            "stall_terminated",
            {"qid": question_id, "rounds": rounds},
        )
        self.stall.clear(question_id)
        if self.subagent_runtime is not None:
            child_run_id, _checkpoint = await latest_subagent_pointers(
                self.ledger, question_id
            )
            if child_run_id:
                try:
                    await self.subagent_runtime.cancel(child_run_id, "stall_terminated")
                except Exception:  # noqa: BLE001 — stall path must still split
                    pass
        # SPLIT if depth allows, else abandon (both handled by _do_split).
        await self._do_split(question)

    async def _register_round_outcome(
        self,
        results: list[WorkerResult],
    ) -> None:
        """Stop a run when every assigned worker repeatedly fails."""
        if not results:
            return
        rounds = self.stall.record_round(
            all(result.status == "failed" for result in results)
        )
        if rounds is None:
            return

        reasons = [(result.fail_reason or "unknown")[:200] for result in results]
        payload = {
            "rounds": rounds,
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
            f"all workers failed for {rounds} consecutive rounds"
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
        child_ptrs: dict[str, tuple[str | None, str | None]] = {}
        if settings.config.deep_analysis.subagent_enabled:
            for assignment in assignments:
                child_ptrs[assignment.question_id] = await latest_subagent_pointers(
                    self.ledger, assignment.question_id
                )
        results = await asyncio.gather(
            *[
                self._run_worker(
                    assignment,
                    child_run_id=child_ptrs.get(assignment.question_id, (None, None))[
                        0
                    ],
                    child_checkpoint_id=child_ptrs.get(
                        assignment.question_id, (None, None)
                    )[1],
                )
                for assignment in assignments
            ]
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
            if question is None or result.question_id != assignment.question_id:
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
            before = await snapshot(self.ledger, question)
            if result.subagent_run_id:
                await log_subagent_step(
                    self.ledger,
                    assignment.question_id,
                    run_id=result.subagent_run_id,
                    checkpoint_id=result.subagent_checkpoint_id or None,
                    step_kind=result.subagent_step_kind,
                    status=result.status,
                )
            await self.ledger.commit_blobs(result.blobs)
            # P2: the worker has no ledger, so it flags the skip on its result
            # and the single writer records it here -- the same shape the
            # discarded-claim loop below already uses.
            if result.entailment_skipped:
                # C4: the reason used to be the constant
                # "entailment_unavailable" for all five causes, so a discard
                # count of 0 could not be traced back to *which* thing broke.
                # The worker is the only layer that knows; it now says.
                await self.ledger.log(
                    "entailment_filter_skipped",
                    result.question_id,
                    {
                        "claim_count": len(result.claims),
                        "reason": result.entailment_skipped,
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
            #
            # That same keying is lossy for *token accounting* (C3-m1
            # Finding 2): when `result.claims` holds the same text twice,
            # `_grade()` still runs -- and the agentic judge can still
            # dispatch -- both times, but the second write into `verdicts`
            # overwrites the first. Deriving a token total from
            # `verdicts.values()` after the loop would silently drop the
            # first (real, already-billed-against-the-global-budget) judge
            # dispatch. So the total is accumulated per `_grade()` call
            # here, never read back out of the dict. This does not change
            # what gets graded or how many times -- only how the spend is
            # summed; deduping the loop itself is a separate decision with
            # its own measurement implications (it would change which
            # claims get judged), left untouched here.
            verdicts = {}
            judge_tokens_spent = 0
            for claim in result.claims:
                verdict = await self._grade(claim, value_est, result.question_id)
                judge_tokens_spent += verdict.tokens_spent
                verdicts[claim.text] = verdict
            await self.ledger.commit_pass(
                result.question_id,
                result,
                verdicts,
                judge_tokens_spent=judge_tokens_spent,
            )
            await self._regrade_pending(result.question_id, value_est)
            # D15: assess progress and trip the stall valve if this
            # question has made none for max_stall_rounds in a row.
            progressed = await made_progress(
                self.ledger, assignment.question_id, before
            )
            if result.subagent_step_kind == "continuing":
                progressed = True
            await self._register_progress(assignment.question_id, progressed)
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

    async def _finalize(self, root_id: str) -> str:
        """Reduce the tree, resolve conflicts, run at most one bounded
        reinvestigation round, then delegate report writing (assemble or
        compose → render → grade, the retry loop and the failure appendix) to
        `ReportWriter.write`. Never exits empty-handed (§6.8)."""
        config = settings.config.deep_analysis
        summaries, reinvestigate = await reduce_and_resolve(
            self.synthesizer, self.ledger, config.source_tiers, root_id
        )
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
            already_reinvestigated = await has_event_fn("conflict_reinvestigation")
        else:
            # Minimal ledger doubles fall back to the in-memory counter.
            already_reinvestigated = (
                self._reinvestigation_count >= config.conflict_reinvestigation_cap
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
                summaries, reinvestigate = await reduce_and_resolve(
                    self.synthesizer, self.ledger, config.source_tiers, root_id
                )
            except TokenBudgetExhausted as exc:
                await self._mark_stop_reason(exc)

        return await self.report_writer.write(root_id, summaries)

    async def run(self, root_text: str) -> dict[str, str]:
        await self._install_token_budget()
        with token_budget_scope(self.token_budget):
            try:
                recovered = await self.ledger.recover()
                if recovered:
                    # 원장에도 적는다. `_emit` 만으로는 **job 경로에서 이 사실이
                    # 사라진다** -- `jobs.py` 가 event_sink 를 의도적으로 배선하지
                    # 않으므로(중복 적재 방지) 싱크는 인라인 실행에서만 산다.
                    # 프론트는 원장 스트림만 읽으므로 `activityLabel()` 의
                    # `recovered` 분기가 절대 뜨지 않는 죽은 코드였다.
                    #
                    # 재개마다 1건씩 남는 것이 맞다 -- 두 번 재개하며 각각 회수했다면
                    # 그것은 서로 다른 두 사건이다.
                    await self.ledger.log("recovered", None, {"questions": recovered})
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
