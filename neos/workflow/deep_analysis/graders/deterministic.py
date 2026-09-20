"""Deterministic truthfulness gate; this module performs no network I/O."""

from __future__ import annotations

from ..models import ProposedClaim, Verdict
from ..text_norm import excerpt_match_score
from .computed import grade_computed


class DeterministicGrader:
    def __init__(
        self,
        ledger,
        *,
        quote_threshold: float,
        confidence_cap: dict[int, float],
        reexecutor=None,
    ) -> None:
        self.ledger = ledger
        self.quote_threshold = quote_threshold
        self.confidence_cap = confidence_cap
        # 계산 클레임에만 쓰인다. quote 만 오는 배포에서는 None 이어도 되고,
        # 계산 클레임이 도착하면 `grade_computed` 가 배선 실수로 터뜨린다.
        self.reexecutor = reexecutor

    def _confidence_limit(self, source_count: int) -> float:
        if source_count >= 3:
            return self.confidence_cap[3]
        return self.confidence_cap[source_count]

    async def grade(self, claim: ProposedClaim) -> Verdict:
        # 계산 클레임의 증거는 `evidence` 가 아니라 `computation` 에 있다.
        # 아래 quote 규칙을 그대로 돌리면 "근거 없음" 이라고 답하게 된다.
        if claim.kind == "computed":
            return await grade_computed(
                claim,
                ledger=self.ledger,
                confidence_cap=self.confidence_cap,
                reexecutor=self.reexecutor,
            )
        source_urls = {evidence.source_url for evidence in claim.evidence}
        diagnostics = {
            "deterministic": "rejected",
            "deterministic_code": "",
            "evidence_count": len(claim.evidence),
            "source_count": len(source_urls),
            "fetched_source_count": 0,
            "dead_source_count": 0,
            "excerpt_chars": sum(len(evidence.excerpt) for evidence in claim.evidence),
            "best_quote_score": None,
            "quote_threshold": self.quote_threshold,
        }

        if not claim.evidence:
            diagnostics["deterministic_code"] = "E_NO_EVIDENCE"
            return Verdict(
                ok=False,
                code="E_NO_EVIDENCE",
                detail="no evidence attached",
                diagnostics=diagnostics,
            )

        observations = []
        fetched_urls = set()
        dead_urls = set()
        best_quote_score = None
        for evidence in claim.evidence:
            blob = await self.ledger.get_blob(evidence.raw_ref)
            is_fetched = blob is not None and 200 <= blob.http_status < 300
            score = None
            if is_fetched:
                fetched_urls.add(evidence.source_url)
                score = excerpt_match_score(
                    evidence.excerpt,
                    blob.raw_text or "",
                    self.quote_threshold,
                )
                best_quote_score = (
                    score if best_quote_score is None else max(best_quote_score, score)
                )
            else:
                dead_urls.add(evidence.source_url)
            observations.append((evidence, blob, is_fetched, score))

        diagnostics.update(
            fetched_source_count=len(fetched_urls),
            dead_source_count=len(dead_urls),
            best_quote_score=best_quote_score,
        )

        for evidence, blob, is_fetched, score in observations:
            if not is_fetched:
                status = None if blob is None else blob.http_status
                diagnostics["deterministic_code"] = "E_SOURCE_DEAD"
                return Verdict(
                    ok=False,
                    code="E_SOURCE_DEAD",
                    detail=f"source fetch status={status}",
                    diagnostics=diagnostics,
                )
            if score is None or score < self.quote_threshold:
                diagnostics["deterministic_code"] = "E_QUOTE_MISMATCH"
                return Verdict(
                    ok=False,
                    code="E_QUOTE_MISMATCH",
                    detail="excerpt not found in fetched source",
                    salvage=evidence.source_url,
                    diagnostics=diagnostics,
                )

        limit = self._confidence_limit(len(source_urls))
        if claim.confidence > limit:
            diagnostics["deterministic_code"] = "E_CONFIDENCE_INFLATED"
            return Verdict(
                ok=False,
                code="E_CONFIDENCE_INFLATED",
                detail=f"{claim.confidence} exceeds source cap {limit}",
                salvage="; ".join(sorted(source_urls)),
                diagnostics=diagnostics,
            )

        diagnostics["deterministic"] = "passed"
        return Verdict(ok=True, diagnostics=diagnostics)
