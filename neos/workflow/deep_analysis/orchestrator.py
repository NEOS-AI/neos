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


class Orchestrator:
    def __init__(
        self,
        session,
        run_id: str,
        worker_factory,
        grader,
        *,
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

    async def _run_worker(self, assignment: Assignment) -> WorkerResult:
        worker = self.worker_factory()  # A1: fresh instance per assignment
        try:
            return await asyncio.wait_for(
                worker.investigate(
                    assignment.brief,
                    assignment.effort,
                    assignment.question_id,
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

    def _partition(self, picks):
        assignments: list[Assignment] = []
        splits = []
        config = settings.config.deep_analysis
        for question, effort in picks:
            if effort == Effort.SPLIT:
                splits.append(question)
                continue
            brief = render(
                "worker_brief",
                question_text=question.text,
                verified_summaries="(없음)",
                dead_ends="(없음)",
                repair_count=0,
                repairs="(없음)",
                token_cap=config.effort[effort.value].token_cap,
            )
            assignments.append(Assignment(question.id, brief, effort))
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
                assignments, splits = self._partition(picks)

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
                for result in results:  # P2: 순차 커밋 (single-writer)
                    await self.ledger.commit_blobs(result.blobs)
                    verdicts = {}
                    for claim in result.claims:
                        verdicts[claim.text] = await self.grader.grade(claim)
                    await self.ledger.commit_pass(
                        result.question_id,
                        result,
                        verdicts,
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
