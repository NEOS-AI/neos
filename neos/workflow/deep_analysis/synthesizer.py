"""M1 single-layer synthesis over verified claims only."""

from __future__ import annotations

from neos.config.settings import settings

from .llm import call_llm
from .prompt_loader import render


class Synthesizer:
    def __init__(
        self,
        ledger,
        *,
        llm_call=call_llm,
        llm_client=None,
        cassette=None,
    ) -> None:
        self.ledger = ledger
        self.llm_call = llm_call
        self.llm_client = llm_client
        self.cassette = cassette

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
        response = await self.llm_call(
            config.models.synth,
            prompt,
            max_tokens=config.synthesis_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
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
