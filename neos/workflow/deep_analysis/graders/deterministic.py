"""Deterministic truthfulness gate; this module performs no network I/O."""

from __future__ import annotations

from ..models import ProposedClaim, Verdict
from ..text_norm import excerpt_matches


class DeterministicGrader:
    def __init__(
        self,
        ledger,
        *,
        quote_threshold: float,
        confidence_cap: dict[int, float],
    ) -> None:
        self.ledger = ledger
        self.quote_threshold = quote_threshold
        self.confidence_cap = confidence_cap

    def _confidence_limit(self, source_count: int) -> float:
        if source_count >= 3:
            return self.confidence_cap[3]
        return self.confidence_cap[source_count]

    async def grade(self, claim: ProposedClaim) -> Verdict:
        if not claim.evidence:
            return Verdict(
                ok=False,
                code="E_NO_EVIDENCE",
                detail="no evidence attached",
            )

        for evidence in claim.evidence:
            blob = await self.ledger.get_blob(evidence.raw_ref)
            if blob is None or not 200 <= blob.http_status < 300:
                status = None if blob is None else blob.http_status
                return Verdict(
                    ok=False,
                    code="E_SOURCE_DEAD",
                    detail=f"source fetch status={status}",
                )
            if not excerpt_matches(
                evidence.excerpt,
                blob.raw_text or "",
                self.quote_threshold,
            ):
                return Verdict(
                    ok=False,
                    code="E_QUOTE_MISMATCH",
                    detail="excerpt not found in fetched source",
                    salvage=evidence.source_url,
                )

        source_urls = {
            evidence.source_url for evidence in claim.evidence
        }
        limit = self._confidence_limit(len(source_urls))
        if claim.confidence > limit:
            return Verdict(
                ok=False,
                code="E_CONFIDENCE_INFLATED",
                detail=f"{claim.confidence} exceeds source cap {limit}",
                salvage="; ".join(sorted(source_urls)),
            )

        return Verdict(ok=True)
