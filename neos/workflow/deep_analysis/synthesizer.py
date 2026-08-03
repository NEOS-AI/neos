"""M1 single-layer synthesis over verified claims only."""

from __future__ import annotations

from neos.config.model_routing import resolve_model
from neos.config.settings import settings

from .llm import call_json, call_llm
from .models import ConflictNote, NodeSummary
from .prompt_loader import render
from .token_budget import TokenBudgetExhausted


class Synthesizer:
    def __init__(
        self,
        ledger,
        *,
        llm_call=call_llm,
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
        has_content = bool(root_answer.strip()) or bool(child_blocks)
        if caveats:
            caveats_text = "\n".join(caveats)
        elif has_content:
            caveats_text = "(없음)"
        else:
            caveats_text = "검증된 클레임을 확보하지 못함"
        prompt = render(
            "final_compose",
            root_summary=root_answer or "(요약 없음)",
            child_summaries="\n".join(child_blocks) or "(검증된 발견 없음)",
            caveats=caveats_text,
        )
        config = settings.config.deep_analysis
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.synth,
        ).model
        try:
            response = await self.llm_call(
                synth_model,
                prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="report_assembly",
            )
        except TokenBudgetExhausted:
            return self.deterministic_report(
                root_summary,
                child_summaries,
                caveats,
            )
        qid = root_summary.question_id if root_summary is not None else ""
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
        prompt = render(
            "node_summary",
            question_id=question.id,
            question_text=question.text,
            verified_claims="\n".join(claim_lines) or "(없음)",
            child_summaries="\n".join(child_lines) or "(없음)",
        )
        config = settings.config.deep_analysis
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.synth,
        ).model
        try:
            data, resp = await self.json_call(
                synth_model,
                prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="node_reduction",
            )
        except TokenBudgetExhausted:
            joined = " ".join(c.answer for c in child_summaries) or ""
            return NodeSummary(
                question_id=question.id,
                answer=joined,
                key_claim_ids=[],
                confidence=0.0,
                caveats=["token_budget_exhausted"],
                conflicts=[],
            )
        except Exception:
            joined = " ".join(c.answer for c in child_summaries) or ""
            return NodeSummary(
                question_id=question.id,
                answer=joined,
                key_claim_ids=[],
                confidence=0.0,
                caveats=["node_summary_unparseable"],
                conflicts=[],
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
