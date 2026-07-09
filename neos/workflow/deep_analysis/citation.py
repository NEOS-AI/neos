"""Deterministic citation resolution for verified claim markers."""

from __future__ import annotations

import re


_MARKER = re.compile(r"\[C:([0-9a-f]{8})\]")
_SOURCE_HEADING = re.compile(r"(?m)^## 출처\s*$")


class OrphanCitationError(ValueError):
    code = "E_ORPHAN_CITE"

    def __init__(self, claim_id: str) -> None:
        self.claim_id = claim_id
        super().__init__(f"{self.code}: {claim_id}")


class CitationRenderer:
    def __init__(self, ledger) -> None:
        self.ledger = ledger

    async def render(self, draft: str) -> str:
        claim_ids = list(dict.fromkeys(_MARKER.findall(draft)))
        footnotes: list[str] = []

        for number, claim_id in enumerate(claim_ids, start=1):
            claim = await self.ledger.get_claim(claim_id)
            if claim is None or claim.status != "verified":
                raise OrphanCitationError(claim_id)

            verified = await self.ledger.verified_claims(
                claim.question_id
            )
            urls: list[str] = []
            for stored_claim, evidence_rows in verified:
                if stored_claim.id != claim_id:
                    continue
                for evidence in evidence_rows:
                    if evidence.source_url not in urls:
                        urls.append(evidence.source_url)

            draft = draft.replace(f"[C:{claim_id}]", f"[{number}]")
            footnotes.append(
                f"[{number}] {'; '.join(urls) or '(출처 없음)'}"
            )

        if not footnotes:
            return draft

        footnote_block = "\n".join(footnotes)
        if _SOURCE_HEADING.search(draft):
            return f"{draft.rstrip()}\n{footnote_block}\n"
        return f"{draft.rstrip()}\n\n## 출처\n{footnote_block}\n"
