"""M1 sequential SCOUT orchestration loop."""

from __future__ import annotations

import asyncio
import inspect

from neos.config.settings import settings

from .budgeter import Budgeter
from .citation import CitationRenderer, OrphanCitationError
from .conflict import resolve_conflicts
from .ledger import Ledger
from .llm import call_json
from .models import Assignment, Effort, NodeSummary, Verdict, WorkerResult
from .prompt_loader import render
from .synthesizer import Synthesizer


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
        parallel_workers: int | None = None,
        max_depth: int | None = None,
        max_stall_rounds: int | None = None,
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
        self.budgeter = Budgeter(
            global_token_cap=self.global_token_cap,
            max_depth=self.max_depth,
            parallel_workers=self.parallel_workers,
        )
        self._split_decompose = self._default_split_decompose

    async def _emit(self, kind: str, payload: dict) -> None:
        if self.event_sink is not None:
            await _maybe_await(self.event_sink(kind, payload))

    async def _checkpoint(self) -> None:
        if self.checkpoint is not None:
            await _maybe_await(self.checkpoint())

    async def _grade(self, claim, value_est):
        """Two-stage grading: deterministic tier first; only claims that pass
        it (and only when an agentic grader is configured) proceed to the
        agentic semantic tier. A deterministic failure short-circuits so the
        expensive judge is never invoked on already-rejected claims."""
        verdict = await self.grader.grade(claim)  # deterministic first
        if not verdict.ok or self.agentic_grader is None:
            return verdict
        return await self.agentic_grader.grade(claim, value_est)  # agentic tier

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
        prompt = render(
            "decompose",
            question_text=root_text,
            prior_findings="(없음)",
            dead_ends="(없음)",
        )
        data, _response = await call_json(
            config.models.dig,
            prompt,
            max_tokens=config.decompose_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
        )
        return list(data.get("subquestions", []))[:7]

    async def _default_split_decompose(self, text, verified_summaries, dead_ends):
        config = settings.config.deep_analysis
        prompt = render(
            "decompose",
            question_text=text,
            prior_findings=verified_summaries,
            dead_ends="\n".join(dead_ends) if dead_ends else "(없음)",
        )
        data, _response = await call_json(
            config.models.dig,
            prompt,
            max_tokens=config.decompose_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
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
            brief = render(
                "worker_brief",
                question_text=question.text,
                verified_summaries="(없음)",
                dead_ends="(없음)",
                repair_count=repair_count,
                repairs=repairs_rendered,
                token_cap=config.effort[effort.value].token_cap,
            )
            assignments.append(
                Assignment(question.id, brief, effort, repairs)
            )
        return assignments, splits

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
            for subq in result.proposed_subquestions:  # M3 연기: 로깅만
                await self.ledger.log(
                    "subq_proposed",
                    result.question_id,
                    {"text": subq},
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
                out.append(summary)
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
        return caveats

    async def _finalize(self, root_id: str) -> str:
        """Reduce the tree, resolve conflicts (with at most one bounded
        reinvestigation round), then assemble → render → grade the report with
        a bounded retry loop. Never exits empty-handed (§6.8): on cap
        exhaustion a failure appendix is attached to the last draft."""
        config = settings.config.deep_analysis
        summaries, reinvestigate = await self._reduce_and_resolve(root_id)
        await self._emit("synth_pass", {"qid": root_id})

        reinvest_cap = config.conflict_reinvestigation_cap
        if reinvestigate and self._reinvestigation_count < reinvest_cap:
            self._reinvestigation_count += 1
            target = reinvestigate[0]
            await self.ledger.log(
                "conflict_reinvestigation",
                target,
                {"qids": reinvestigate},
            )
            try:
                await self.ledger._transition(target, "open")
            except Exception:  # noqa: BLE001
                # Reopening a terminal (resolved/split/abandoned) question is
                # illegal; the extra round still runs for any other open work,
                # then both-sides annotations stand.
                pass
            await self._run_round()
            summaries, reinvestigate = await self._reduce_and_resolve(root_id)

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
        for attempt in range(cap + 1):
            draft = await self.synthesizer.assemble(
                root_summary, child_summaries, caveats
            )
            last = draft
            try:
                report = await self.citation_renderer.render(draft)
            except OrphanCitationError:
                await self.ledger.log(
                    "report_graded",
                    root_id,
                    {
                        "ok": False,
                        "code": OrphanCitationError.code,
                        "attempt": attempt,
                    },
                )
                continue  # AC-c: orphan citation → re-assemble
            verdict = (
                await self.report_grader.grade(report, root_id)
                if self.report_grader is not None
                else Verdict(ok=True)
            )
            if verdict.ok:
                await self.ledger.log(
                    "report_graded",
                    root_id,
                    {"ok": True, "attempt": attempt},
                )
                await self.ledger.complete_run()
                return report
            await self.ledger.log(
                "report_graded",
                root_id,
                {"ok": False, "code": verdict.code, "attempt": attempt},
            )

        # Cap exhausted — no empty-handed exit (§6.8): attach a failure
        # appendix to the last draft (best-effort raw text).
        report = (last or "") + (
            "\n\n## 부록: 미해결 사유\n조립/채점 재시도 캡 소진."
        )
        await self.ledger.complete_run()
        return report

    async def run(self, root_text: str) -> dict[str, str]:
        try:
            recovered = await self.ledger.recover()
            if recovered:
                await self._emit("recovered", {"questions": recovered})
                await self._checkpoint()

            root_id = await self._ensure_root(root_text)

            while not await self.budgeter.should_stop(self.ledger):
                if not await self._run_round():
                    break

            report = await self._finalize(root_id)
            await self._checkpoint()
            await self._emit(
                "completed",
                {"run_id": self.run_id},
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
            raise
