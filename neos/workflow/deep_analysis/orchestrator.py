"""M1 sequential SCOUT orchestration loop."""

from __future__ import annotations

import asyncio
import inspect

from neos.config.settings import settings

from .budgeter import Budgeter
from .citation import CitationRenderer
from .ledger import Ledger
from .llm import call_json
from .models import Assignment, Effort, WorkerResult
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
        event_sink=None,
        checkpoint=None,
        llm_client=None,
        cassette=None,
        global_token_cap: int | None = None,
        parallel_workers: int | None = None,
        max_depth: int | None = None,
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

    async def run(self, root_text: str) -> dict[str, str]:
        try:
            recovered = await self.ledger.recover()
            if recovered:
                await self._emit("recovered", {"questions": recovered})
                await self._checkpoint()

            root_id = await self._ensure_root(root_text)

            while not await self.budgeter.should_stop(self.ledger):
                picks = await self.budgeter.select(self.ledger)
                if not picks:
                    break
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
                    question = await self.ledger.get_question(
                        result.question_id
                    )
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
                        continue
                    value_est = question.value_est
                    await self.ledger.commit_blobs(result.blobs)
                    verdicts = {}
                    for claim in result.claims:
                        verdicts[claim.text] = await self._grade(
                            claim, value_est
                        )
                    await self.ledger.commit_pass(
                        result.question_id,
                        result,
                        verdicts,
                    )
                    await self._regrade_pending(
                        result.question_id, value_est
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

            draft = await self.synthesizer.reduce(root_id)
            await self._emit("synth_pass", {"qid": root_id})
            await self._checkpoint()

            report = await self.citation_renderer.render(draft)
            await self.ledger.log(
                "report_graded",
                root_id,
                {"ok": True},
            )
            await self.ledger.complete_run()
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
