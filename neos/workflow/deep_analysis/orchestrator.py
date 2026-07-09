"""M1 sequential SCOUT orchestration loop."""

from __future__ import annotations

import inspect

from neos.config.settings import settings

from .budgeter import Budgeter
from .citation import CitationRenderer
from .ledger import Ledger
from .llm import call_json
from .prompt_loader import render
from .synthesizer import Synthesizer


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


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
        self.budgeter = Budgeter()
        self.global_token_cap = (
            settings.DEEP_ANALYSIS_GLOBAL_TOKEN_CAP
            if global_token_cap is None
            else global_token_cap
        )

    async def _emit(self, kind: str, payload: dict) -> None:
        if self.event_sink is not None:
            await _maybe_await(self.event_sink(kind, payload))

    async def _checkpoint(self) -> None:
        if self.checkpoint is not None:
            await _maybe_await(self.checkpoint())

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

        subquestions = await self.decompose_fn(root_text)
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

    async def run(self, root_text: str) -> dict[str, str]:
        try:
            recovered = await self.ledger.recover()
            if recovered:
                await self._emit("recovered", {"questions": recovered})
                await self._checkpoint()

            root_id = await self._ensure_root(root_text)
            config = settings.config.deep_analysis

            while True:
                picks = await self.budgeter.select(self.ledger, k=1)
                if await self.budgeter.should_stop(self.ledger):
                    break
                if not picks:
                    break

                question, effort = picks[0]
                await self.ledger._transition(
                    question.id,
                    "investigating",
                )
                await self._checkpoint()

                brief = render(
                    "worker_brief",
                    question_text=question.text,
                    verified_summaries="(없음)",
                    dead_ends="(없음)",
                    repair_count=0,
                    repairs="(없음)",
                    token_cap=config.effort[effort.value].token_cap,
                )
                worker = self.worker_factory()
                result = await worker.investigate(
                    brief,
                    effort,
                    question.id,
                )

                await self.ledger.commit_blobs(result.blobs)
                await self._checkpoint()

                verdicts = {}
                for claim in result.claims:
                    verdicts[claim.text] = await self.grader.grade(claim)

                await self.ledger.commit_pass(
                    question.id,
                    result,
                    verdicts,
                )
                await self._emit(
                    "pass_completed",
                    {
                        "qid": question.id,
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
