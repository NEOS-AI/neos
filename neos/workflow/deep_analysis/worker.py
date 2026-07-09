"""Stateless research worker: (brief, effort) -> WorkerResult."""

from __future__ import annotations

import json
from typing import Callable

from neos.config.settings import settings

from .fetch import fetch_url
from .llm import call_json
from .models import (
    Effort,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    WorkerResult,
)


class Worker:
    def __init__(
        self,
        search_fn: Callable,
        *,
        fetch_fn=fetch_url,
        llm_client=None,
        http_client=None,
        cassette=None,
    ) -> None:
        self.search_fn = search_fn
        self.fetch_fn = fetch_fn
        self.llm_client = llm_client
        self.http_client = http_client
        self.cassette = cassette
        self._claims: list[ProposedClaim] = []
        self._blobs: list[ProposedBlob] = []
        self._tokens = 0
        self._model = ""

    def flush_partial(self, question_id: str) -> WorkerResult:
        return WorkerResult(
            question_id=question_id,
            status="partial",
            claims=list(self._claims),
            blobs=list(self._blobs),
            tokens_spent=self._tokens,
            model=self._model,
        )

    async def _search(self, query: str, limit: int) -> list[dict]:
        async def produce():
            return await self.search_fn(query, k=limit)

        if self.cassette is None:
            return await produce()
        return await self.cassette.remember(
            "search",
            {"query": query, "limit": limit},
            produce,
        )

    async def investigate(
        self,
        brief: str,
        effort: Effort,
        question_id: str,
    ) -> WorkerResult:
        if effort not in {Effort.SCOUT, Effort.DIG}:
            raise ValueError(f"worker cannot execute effort {effort.value}")

        self._claims = []
        self._blobs = []
        self._tokens = 0

        config = settings.config.deep_analysis
        self._model = (
            config.models.scout
            if effort == Effort.SCOUT
            else config.models.dig
        )
        effort_config = config.effort[effort.value]

        search_results = await self._search(
            brief,
            config.search_result_limit,
        )
        fetched_by_url: dict[str, ProposedBlob] = {}
        for search_result in search_results:
            url = search_result.get("url", "")
            if not url or url in fetched_by_url:
                continue
            blob = await self.fetch_fn(
                url,
                client=self.http_client,
                cassette=self.cassette,
            )
            fetched_by_url[url] = blob
            self._blobs.append(blob)

        evidence_blocks = []
        for url, blob in fetched_by_url.items():
            source_url = json.dumps(url, ensure_ascii=False)
            raw_ref = json.dumps(blob.content_hash)
            evidence_blocks.append(
                f"<evidence source_url={source_url} raw_ref={raw_ref}>\n"
                f"{blob.raw_text[:config.evidence_context_chars]}\n"
                "</evidence>"
            )
        evidence_context = "\n\n".join(evidence_blocks) or "(검색 결과 없음)"
        prompt = brief.replace("{fetched_evidence}", evidence_context)

        data, response = await call_json(
            self._model,
            prompt,
            max_tokens=min(
                effort_config.token_cap,
                config.worker_max_output_tokens,
            ),
            client=self.llm_client,
            cassette=self.cassette,
        )
        self._tokens += response.input_tokens + response.output_tokens

        for raw_claim in data.get("claims", []):
            evidence_items = []
            for raw_evidence in raw_claim.get("evidence", []):
                source_url = str(raw_evidence.get("source_url", ""))
                fetched = fetched_by_url.get(source_url)
                evidence_items.append(
                    ProposedEvidence(
                        source_url=source_url,
                        excerpt=str(raw_evidence.get("excerpt", "")),
                        raw_ref=(
                            fetched.content_hash if fetched is not None else ""
                        ),
                    )
                )
            self._claims.append(
                ProposedClaim(
                    text=str(raw_claim["text"]),
                    confidence=float(raw_claim.get("confidence", 0.0)),
                    evidence=evidence_items,
                )
            )

        raw_status = data.get("status", "completed")
        status = (
            raw_status
            if raw_status in {"completed", "partial", "failed"}
            else "failed"
        )
        self_assessment = min(
            1.0,
            max(0.0, float(data.get("self_assessment", 0.0))),
        )
        return WorkerResult(
            question_id=question_id,
            status=status,
            claims=list(self._claims),
            blobs=list(self._blobs),
            proposed_subquestions=list(
                data.get("proposed_subquestions", [])
            ),
            dead_ends=list(data.get("dead_ends", [])),
            tokens_spent=self._tokens,
            model=self._model,
            self_assessment=self_assessment,
            fail_reason=str(data.get("fail_reason", "")),
        )
