"""M1 single-layer synthesis over verified claims only."""

from __future__ import annotations

from neos.config.model_routing import resolve_model
from neos.config.settings import settings

from .llm import call_json, call_text
from .models import ConflictNote, NodeSummary
from .prompt_clamp import clamp_prompt
from .prompt_loader import render
from .token_budget import TokenBudgetExhausted


def _degradation_reason(exc: TokenBudgetExhausted) -> str:
    """강등 이벤트의 `reason` -- 예외 타입이 아니라 거절 사유에서 온다.

    이 두 자리는 `"token_budget_exhausted"` 를 하드코딩하고 있었다.
    `reserve` 가 캡 소진과 `input_bound` 거절에 같은 예외를 던지므로, 여유가
    남은 채 거절된 run 도 "예산 소진"으로 기록됐다 -- G9 가 정지 사유에서
    없앤 것과 같은 종류의 거짓이다.

    `tier_floor` 는 옛 문자열을 그대로 낸다. 이미 원장에 쌓인 강등 이벤트가
    그 어휘를 쓰고 있어 경계 전후 집계가 이어져야 하기 때문이다. 새 문자열은
    지금까지 존재하지 않던 구별에만 붙는다.
    """
    if exc.cause == "input_bound":
        return "input_bound"
    return "token_budget_exhausted"


class Synthesizer:
    def __init__(
        self,
        ledger,
        *,
        # `call_text` 는 잘린 조립에 한 번 더 큰 시도를 준다. 예전 기본값
        # `call_llm` 은 잘림을 기록만 했고, 그래서 조립만 회복하지 못했다
        # (2026-08-08 표본 #2: 18/18 잘림, 필수 마지막 절이 매번 소실).
        llm_call=call_text,
        json_call=call_json,
        llm_client=None,
        cassette=None,
        synthesis_max_tokens: int | None = None,
    ) -> None:
        self.ledger = ledger
        self.llm_call = llm_call
        self.json_call = json_call
        self.llm_client = llm_client
        self.cassette = cassette
        # None means "use the global default" so every existing construction
        # site keeps working; service.py passes the profile-resolved value.
        self._synthesis_max_tokens = synthesis_max_tokens

    @property
    def synthesis_max_tokens(self) -> int:
        if self._synthesis_max_tokens is not None:
            return self._synthesis_max_tokens
        return settings.config.deep_analysis.synthesis_max_tokens

    @property
    def assembly_input_allowance(self) -> int:
        """Input bytes report_assembly's prompt may occupy.

        Derived here rather than injected: `synthesis_max_tokens` above is
        already the profile-resolved value, and the ratio is global policy.
        Threading two more constructor arguments through service.py would
        give the same number two sources.
        """
        ratio = settings.config.deep_analysis.assembly_input_ratio
        return int(ratio * self.synthesis_max_tokens)

    @property
    def reduction_input_allowance(self) -> int:
        ratio = settings.config.deep_analysis.reduction_input_ratio
        return int(ratio * self.synthesis_max_tokens)

    async def _log_clamp(self, stage: str, qid: str, result, allowance: int) -> None:
        """Record a clamp only when it actually cut something.

        Logging every call would bury the signal: the interesting event is
        a finalization prompt that did not fit, not one that did.
        """
        if not (result.clamped or result.exhausted):
            return
        await self.ledger.log(
            "finalization_prompt_clamped",
            qid,
            {
                "stage": stage,
                "bound_before": result.bound_before,
                "bound_after": result.bound_after,
                "allowance": allowance,
                "dropped_primary": result.dropped_primary,
                "dropped_secondary": result.dropped_secondary,
                "exhausted": result.exhausted,
            },
        )

    async def reduce(self, root_id: str) -> str:
        root = await self.ledger.root_question()
        if root is None or root.id != root_id:
            raise KeyError(f"root question not found: {root_id}")

        claim_blocks: list[str] = []
        caveat_lines: list[str] = []
        children = await self.ledger.children(root_id)
        questions = [root, *children]
        for question in questions:
            for claim, evidence_rows in await self.ledger.verified_claims(
                question.id
            ):
                evidence = "\n".join(
                    f"<evidence>{row.excerpt}</evidence>"
                    for row in evidence_rows
                )
                claim_blocks.append(
                    f"- 질문: {question.text}\n"
                    f"  클레임 [C:{claim.id}]: {claim.text}\n"
                    f"  confidence: {claim.confidence}\n"
                    f"  {evidence}"
                )
            for text in await self.ledger.unverified_and_deadends(
                question.id
            ):
                caveat_lines.append(f"미확인: {text}")

        for question in await self.ledger.questions():
            if question.status == "abandoned":
                caveat_lines.append(f"미조사: {question.text}")

        if caveat_lines:
            caveats = "\n".join(caveat_lines)
        elif claim_blocks:
            caveats = "(없음)"
        else:
            caveats = "검증된 클레임을 확보하지 못함"
        prompt = render(
            "final_compose",
            root_summary=root.text,
            child_summaries="\n".join(claim_blocks)
            or "(검증된 발견 없음)",
            caveats=caveats,
        )
        config = settings.config.deep_analysis
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.synth,
        ).model
        response = await self.llm_call(
            synth_model,
            prompt,
            max_tokens=self.synthesis_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
            stage="report_assembly",
        )
        await self.ledger.log(
            "synth_pass",
            root_id,
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "verified_claims": len(claim_blocks),
            },
        )
        return response.text

    async def assemble(
        self,
        root_summary: NodeSummary | None,
        child_summaries: list[NodeSummary],
        caveats: list[str],
    ) -> str:
        """Final compose (§6.8) over the root ``NodeSummary`` + direct-child
        ``NodeSummary`` answers + collected caveats.

        This is the M4 assembly seam driven by the orchestrator's
        ``_finalize`` retry loop. ``reduce`` (single-layer, M1) is kept intact
        as a backward-compatible path for callers/tests that still summarize
        straight from the ledger; ``assemble`` instead composes from
        already-reduced hierarchical ``NodeSummary`` objects.
        """
        root_answer = root_summary.answer if root_summary is not None else ""
        child_blocks = [
            f"- [{child.question_id}] {child.answer}"
            for child in child_summaries
        ]
        config = settings.config.deep_analysis
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.synth,
        ).model
        qid = root_summary.question_id if root_summary is not None else ""

        def render_assembly(blocks: list[str], notes: list[str]) -> str:
            # Computed from this call's own `blocks`, not the pre-clamp
            # `child_blocks` -- the clamp can drop every child block and
            # leave `root_answer` empty too, and this must reflect that
            # (F10): the closure is pure with respect to its arguments.
            has_content = bool(root_answer.strip()) or bool(blocks)
            if notes:
                caveats_text = "\n".join(notes)
            elif has_content:
                caveats_text = "(없음)"
            else:
                caveats_text = "검증된 클레임을 확보하지 못함"
            return render(
                "final_compose",
                root_summary=root_answer or "(요약 없음)",
                child_summaries="\n".join(blocks) or "(검증된 발견 없음)",
                caveats=caveats_text,
            )

        clamp = clamp_prompt(
            model=synth_model,
            allowance=self.assembly_input_allowance,
            render_prompt=render_assembly,
            primary=child_blocks,
            secondary=list(caveats),
        )
        await self._log_clamp(
            "report_assembly", qid, clamp, self.assembly_input_allowance
        )
        try:
            response = await self.llm_call(
                synth_model,
                clamp.prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="report_assembly",
            )
        except TokenBudgetExhausted as exc:
            # Falling back to a template is correct -- no empty-handed exit
            # (§6.8) -- but it must not look like success. Every recorded run
            # took this path and nothing said so.
            await self.ledger.log(
                "report_assembly_degraded",
                qid,
                {"reason": _degradation_reason(exc)},
            )
            return self.deterministic_report(
                root_summary,
                child_summaries,
                caveats,
            )
        if not response.text.strip():
            # A blank assembly used to log `synth_pass` and return "" -- the
            # call succeeded, so nothing looked wrong. Measured 2026-08-08
            # (sample #2, `a82648e3`): three blank assemblies, three
            # `synth_pass` events, and a report that was the empty string.
            # S1 counts `synth_pass`, so the one metric that says "an LLM
            # actually wrote a report" was counting reports that did not exist.
            #
            # `report_assembly_degraded` is deliberate rather than a new kind:
            # it is already registered in `_DEGRADATION_KINDS` (ledger.py) and
            # `degradationKind()` (progress.ts), so this reaches the user's
            # screen without touching either copy of that vocabulary.
            await self.ledger.log(
                "report_assembly_degraded",
                qid,
                {"reason": "empty_assembly"},
            )
            return self.deterministic_report(
                root_summary,
                child_summaries,
                caveats,
            )
        await self.ledger.log(
            "synth_pass",
            qid,
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "child_count": len(child_summaries),
            },
        )
        return response.text

    @staticmethod
    def deterministic_report(
        root_summary: NodeSummary | None,
        child_summaries: list[NodeSummary],
        caveats: list[str],
    ) -> str:
        root_answer = (
            root_summary.answer.strip()
            if root_summary is not None and root_summary.answer.strip()
            else "검증된 요약을 확보하지 못했습니다."
        )
        body = "\n\n".join(
            f"### {child.question_id}\n{child.answer}"
            for child in child_summaries
            if child.answer.strip()
        ) or root_answer
        limitations = [*caveats, "전체 심층분석 토큰 상한에 도달했습니다."]
        return (
            f"## 요약\n{root_answer}\n\n"
            f"## 본문\n{body}\n\n"
            "## 한계와 미확인 사항\n"
            + "\n".join(f"- {item}" for item in limitations)
            + "\n\n## 출처\n"
        )

    async def reduce_node(
        self, question, child_summaries: list[NodeSummary]
    ) -> NodeSummary:
        """Summarize ONE node from its own verified claims + direct
        children's NodeSummary.answer strings only (never grandchild raw
        claims). This bounded per-node context is the AC-a invariant.
        """
        pairs = await self.ledger.verified_claims(question.id)
        claim_lines = []
        for claim, evidence_rows in pairs:
            ev = " ".join(
                f"<evidence>{row.excerpt}</evidence>" for row in evidence_rows
            )
            claim_lines.append(
                f"[C:{claim.id}] {claim.text} (conf {claim.confidence}) {ev}"
            )
        child_lines = [
            f"[{c.question_id}] {c.answer}" for c in child_summaries
        ]
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=settings.config.deep_analysis.models.synth,
        ).model

        def render_node(claims: list[str], children: list[str]) -> str:
            return render(
                "node_summary",
                question_id=question.id,
                question_text=question.text,
                verified_claims="\n".join(claims) or "(없음)",
                child_summaries="\n".join(children) or "(없음)",
            )

        clamp = clamp_prompt(
            model=synth_model,
            allowance=self.reduction_input_allowance,
            render_prompt=render_node,
            primary=claim_lines,
            secondary=child_lines,
        )
        await self._log_clamp(
            "node_reduction",
            question.id,
            clamp,
            self.reduction_input_allowance,
        )
        prompt = clamp.prompt
        try:
            data, resp = await self.json_call(
                synth_model,
                prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="node_reduction",
            )
        except TokenBudgetExhausted as exc:
            return await self._degraded_summary(
                question, child_summaries, _degradation_reason(exc), pairs
            )
        except Exception:
            return await self._degraded_summary(
                question,
                child_summaries,
                "node_summary_unparseable",
                pairs,
            )
        await self.ledger.log(
            "node_summary",
            question.id,
            {
                "input_tokens": resp.input_tokens,
                "prompt_chars": len(prompt),
                "child_count": len(child_summaries),
                "own_claims": len(pairs),
            },
        )
        conflicts: list[ConflictNote] = []
        for c in data.get("conflicts", []) or []:
            try:
                conflicts.append(
                    ConflictNote(
                        claim_a=c["claim_a"],
                        claim_b=c["claim_b"],
                        nature=c.get("nature", ""),
                    )
                )
            except (KeyError, TypeError, AttributeError):
                # malformed conflict entry (missing keys / wrong shape) --
                # skip it rather than crashing the whole node's summary.
                continue
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        key_claim_ids_raw = data.get("key_claim_ids") or []
        try:
            key_claim_ids = list(key_claim_ids_raw)
        except TypeError:
            key_claim_ids = []
        caveats_raw = data.get("caveats") or []
        try:
            caveats = list(caveats_raw)
        except TypeError:
            caveats = []
        return NodeSummary(
            question_id=question.id,
            answer=str(data.get("answer") or ""),
            key_claim_ids=key_claim_ids,
            confidence=confidence,
            caveats=caveats,
            conflicts=conflicts,
        )

    async def _degraded_summary(
        self,
        question,
        child_summaries: list[NodeSummary],
        reason: str,
        pairs: list | None = None,
    ) -> NodeSummary:
        """Fall back to joining the children's answers, and say so.

        This degradation predates the ledger entry and left no trace, so a
        run whose reductions all degraded was byte-identical to one where
        they all succeeded. That distinction is exactly what tells whether
        isolating the report tier worked: reductions are allowed to degrade,
        the assembly is not.

        `pairs` is the node's own verified claims, and it exists because
        joining children is not a fallback for a **leaf**: a leaf has no
        children, so the join produced `""` and the leaf's verified claims
        vanished. Measured 2026-08-07: most degraded reductions were leaves
        (8 of 10, 11 of 14, 8 of 11 ...), the runs that degraded 67-79% of
        their reductions shipped 0-8 citation markers, and the one that
        degraded 18% shipped 60. With nothing to cite the report gate
        rejected all 18 attempts.

        The deterministic answer keeps `[C:...]` markers so CitationRenderer
        can still resolve them -- these are verified claims by construction,
        so they cannot orphan. It deliberately drops the prompt scaffolding
        (evidence excerpts, confidence) that `reduce_node` builds for the
        model: that is input for an LLM, not prose for a reader.
        """
        await self.ledger.log(
            "node_reduction_degraded",
            question.id,
            {
                "question_id": question.id,
                "child_count": len(child_summaries),
                "reason": reason,
            },
        )
        answer = " ".join(
            c.answer for c in child_summaries if c.answer.strip()
        )
        claim_ids: list[str] = []
        if not answer and pairs:
            answer = " ".join(
                f"[C:{claim.id}] {claim.text}" for claim, _evidence in pairs
            )
            claim_ids = [claim.id for claim, _evidence in pairs]
        return NodeSummary(
            question_id=question.id,
            answer=answer,
            key_claim_ids=claim_ids,
            confidence=0.0,
            caveats=[reason],
            conflicts=[],
        )

    async def reduce_tree(self, root_id: str) -> dict[str, NodeSummary]:
        """Post-order reduce over the question tree rooted at `root_id`.

        Leaves are reduced first, then parents using only their direct
        children's `NodeSummary` (never grandchild raw claims) -- this
        keeps each node's LLM context bounded regardless of subtree size
        (AC-a). `abandoned` questions are excluded entirely (no summary
        is produced for them, nor are they passed to their parent).
        """
        summaries: dict[str, NodeSummary] = {}
        visited: set[str] = set()

        async def visit(qid: str) -> None:
            if qid in visited:
                # cycle / diamond re-encounter -- already reduced (or in
                # progress); skip to avoid unbounded recursion.
                return
            visited.add(qid)
            children = [
                child
                for child in await self.ledger.children(qid)
                if child.status != "abandoned"
            ]
            child_summaries: list[NodeSummary] = []
            for child in children:
                await visit(child.id)
                if child.id in summaries:
                    child_summaries.append(summaries[child.id])
            question = await self.ledger.get_question(qid)
            if question is None or question.status == "abandoned":
                return
            summaries[qid] = await self.reduce_node(question, child_summaries)

        await visit(root_id)
        return summaries
