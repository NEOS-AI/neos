"""Stateless research worker: (brief, effort) -> WorkerResult."""

from __future__ import annotations

import json
import logging
from typing import Callable

from neos.config.model_routing import resolve_model
from neos.config.settings import settings

from .claim_entailment import apply_entailment_results
from .discovery import run_discovery
from .fetch import fetch_url
from .llm import (
    JSONParseError,
    LLMProviderError,
    TruncatedResponseError,
    call_json,
)
from .models import (
    Effort,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    RepairResult,
    WorkerResult,
)
from .pdf_text import PDFExtractionError
from .prompt_loader import render
from .token_budget import TokenBudgetExhausted

_REPAIR_ACTIONS = {"fixed", "weakened", "abandoned"}
_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")
logger = logging.getLogger(__name__)


def _source_bucket(count: int) -> str:
    return str(count) if count < 3 else "3_plus"


def _confidence_limit(source_count: int, caps: dict[int, float]) -> float:
    if source_count == 0:
        return 0.0
    return caps[3 if source_count >= 3 else source_count]


class Worker:
    def __init__(
        self,
        search_fn: Callable,
        *,
        fetch_fn=fetch_url,
        llm_client=None,
        http_client=None,
        cassette=None,
        skill_selector=None,
        confidence_cap: dict[int, float] | None = None,
    ) -> None:
        self.search_fn = search_fn
        self.fetch_fn = fetch_fn
        self.llm_client = llm_client
        self.http_client = http_client
        self.cassette = cassette
        self.skill_selector = skill_selector
        self._confidence_cap = dict(
            confidence_cap
            if confidence_cap is not None
            else settings.config.deep_analysis.confidence_cap
        )
        self._claims: list[ProposedClaim] = []
        self._discarded_claims: list[ProposedClaim] = []
        self._blobs: list[ProposedBlob] = []
        self._tokens = 0
        self._model = ""
        self._confidence_clamped_by_source_count: dict[str, int] = {}
        self._entailment_skipped = False

    def flush_partial(self, question_id: str) -> WorkerResult:
        return WorkerResult(
            question_id=question_id,
            status="partial",
            claims=list(self._claims),
            discarded_claims=list(self._discarded_claims),
            blobs=list(self._blobs),
            tokens_spent=self._tokens,
            model=self._model,
            confidence_clamped_count=sum(
                self._confidence_clamped_by_source_count.values()
            ),
            confidence_clamped_by_source_count=dict(
                self._confidence_clamped_by_source_count
            ),
            entailment_skipped=self._entailment_skipped,
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

    async def _collect_candidates(
        self, search_query: str, effort: Effort, limit: int, *, brief: str = ""
    ) -> list[dict]:
        """Discovery 단계 — URL 후보만 모은다. retrieval은 fetch_fn 독점(P3).

        `search_query`는 검색 엔진에 그대로 들어가는 짧은 질문이고, `brief`는
        LLM tool-calling 경로가 맥락으로 쓰는 프롬프트 전문이다. 둘을 섞으면
        검색이 0건을 반환한다.
        """
        if self.skill_selector is None:
            return await self._search(search_query, limit)

        skills = self.skill_selector.candidates(effort)
        if not skills:
            return await self._search(search_query, limit)

        config = settings.config.deep_analysis
        effort_config = config.effort[effort.value]
        items, tokens = await run_discovery(
            brief or search_query,
            skills,
            search_fn=self.search_fn,
            model=self._model,
            max_tokens=min(effort_config.token_cap, config.worker_max_output_tokens),
            limit=limit,
            client=self.llm_client,
            cassette=self.cassette,
        )
        self._tokens += tokens
        if not items:
            # 스킬이 전부 실패했으면 web_search 단독 경로로 degrade한다.
            return await self._search(search_query, limit)
        return items

    async def investigate(
        self,
        brief: str,
        effort: Effort,
        question_id: str,
        repairs: list[dict] | None = None,
        question_text: str = "",
    ) -> WorkerResult:
        try:
            return await self._investigate(
                brief,
                effort,
                question_id,
                repairs=repairs,
                question_text=question_text,
            )
        except TokenBudgetExhausted:
            return self.flush_partial(question_id)

    async def _investigate(
        self,
        brief: str,
        effort: Effort,
        question_id: str,
        repairs: list[dict] | None = None,
        question_text: str = "",
    ) -> WorkerResult:
        if effort not in {Effort.SCOUT, Effort.DIG}:
            raise ValueError(f"worker cannot execute effort {effort.value}")

        self._claims = []
        self._discarded_claims = []
        self._blobs = []
        self._tokens = 0
        self._confidence_clamped_by_source_count = {}
        self._entailment_skipped = False

        config = settings.config.deep_analysis
        role = "everyday" if effort == Effort.SCOUT else "powerful"
        feature_override = (
            config.models.scout if effort == Effort.SCOUT else config.models.dig
        )
        self._model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role=role,
            feature_override=feature_override,
        ).model
        effort_config = config.effort[effort.value]

        repairs = repairs or []
        if repairs and all(
            r.get("code") == "E_OVERCLAIM" for r in repairs
        ):
            return await self._weaken_only(
                brief, question_id, repairs, effort_config
            )

        # 검색어는 원 질문이어야 한다. brief는 템플릿이 렌더링된 프롬프트
        # 전문(~1KB)이라 그대로 검색 엔진에 넣으면 0건이 돌아온다 --
        # 그러면 fetch할 URL이 없어 모든 클레임이 E_NO_EVIDENCE로 거절된다.
        search_query = question_text or brief
        search_results = await self._collect_candidates(
            search_query,
            effort,
            config.search_result_limit,
            brief=brief,
        )
        fetched_by_url: dict[str, ProposedBlob] = {}
        for search_result in search_results:
            url = search_result.get("url", "")
            if not url or url in fetched_by_url:
                continue
            try:
                blob = await self.fetch_fn(
                    url,
                    client=self.http_client,
                    cassette=self.cassette,
                )
            except PDFExtractionError as exc:
                logger.warning(
                    "Skipping unreadable PDF source: url=%s error_type=%s",
                    url,
                    type(exc).__name__,
                )
                continue
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
            # effort.token_cap is the effort's BUDGET, not a per-response
            # output allowance. Using it here truncated claim-bearing
            # responses mid-JSON at SCOUT's 2000 tokens — 18 of them in the
            # 20260731T130316Z sample — and a truncated response parses to
            # zero claims, so every claim in it was silently lost. The budget
            # is still enforced, by the token budget layer.
            max_tokens=config.worker_max_output_tokens,
            client=self.llm_client,
            cassette=self.cassette,
            stage="worker_analysis",
        )
        self._tokens += response.input_tokens + response.output_tokens

        for raw_claim in data.get("claims", []):
            evidence_items = []
            for raw_evidence in raw_claim.get("evidence", []):
                source_url = str(raw_evidence.get("source_url", ""))
                fetched = fetched_by_url.get(source_url)
                if fetched is None:
                    continue
                evidence_items.append(
                    ProposedEvidence(
                        source_url=source_url,
                        excerpt=str(raw_evidence.get("excerpt", "")),
                        raw_ref=fetched.content_hash,
                    )
                )
            requested_confidence = min(
                1.0,
                max(0.0, float(raw_claim.get("confidence", 0.0))),
            )
            source_count = len(
                {evidence.source_url for evidence in evidence_items}
            )
            confidence_limit = _confidence_limit(
                source_count, self._confidence_cap
            )
            confidence = min(requested_confidence, confidence_limit)
            if requested_confidence > confidence_limit:
                bucket = _source_bucket(source_count)
                assert bucket in _CLAMP_BUCKETS
                self._confidence_clamped_by_source_count[bucket] = (
                    self._confidence_clamped_by_source_count.get(bucket, 0)
                    + 1
                )
            self._claims.append(
                ProposedClaim(
                    text=str(raw_claim["text"]),
                    confidence=confidence,
                    evidence=evidence_items,
                )
            )

        self._claims = await self._refine_claims(self._claims)

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
        repair_results = self._parse_repairs(
            data.get("repairs", []), fetched_by_url
        )
        return WorkerResult(
            question_id=question_id,
            status=status,
            claims=list(self._claims),
            discarded_claims=list(self._discarded_claims),
            blobs=list(self._blobs),
            repairs=repair_results,
            proposed_subquestions=list(
                data.get("proposed_subquestions", [])
            ),
            dead_ends=list(data.get("dead_ends", [])),
            tokens_spent=self._tokens,
            model=self._model,
            self_assessment=self_assessment,
            fail_reason=str(data.get("fail_reason", "")),
            confidence_clamped_count=sum(
                self._confidence_clamped_by_source_count.values()
            ),
            confidence_clamped_by_source_count=dict(
                self._confidence_clamped_by_source_count
            ),
            entailment_skipped=self._entailment_skipped,
        )

    async def _refine_claims(
        self,
        claims: list[ProposedClaim],
    ) -> list[ProposedClaim]:
        if not claims:
            return claims

        config = settings.config.deep_analysis
        claims_json = json.dumps(
            [
                {
                    "index": index,
                    "claim": claim.text,
                    "evidence": [
                        evidence.excerpt for evidence in claim.evidence
                    ],
                }
                for index, claim in enumerate(claims)
            ],
            ensure_ascii=False,
        )
        prompt = render("claim_entailment", claims_json=claims_json)
        try:
            payload, response = await call_json(
                self._model,
                prompt,
                max_tokens=config.entailment_max_output_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="claim_entailment",
                # This call never retried a malformed response and must not
                # start: a second batch costs the same tokens for a response
                # the first attempt already showed the model will not format.
                # The truncation expansion is a separate axis and still runs.
                retries=0,
            )
        except TokenBudgetExhausted:
            # The batch propagates unrefined via `investigate()`'s
            # `flush_partial` -- flag the skip here so that unfiltered batch
            # is never silently mistaken for "entailment found nothing to
            # discard".
            self._entailment_skipped = True
            raise
        except LLMProviderError as exc:
            logger.warning(
                "Claim entailment provider failed: error_type=%s",
                type(exc).__name__,
            )
            self._entailment_skipped = True
            return claims
        except TruncatedResponseError:
            # A filter, not a gate: these claims still face the deterministic
            # and agentic graders. Dropping or rejecting the batch would
            # manufacture the very recall loss the discard measurement exists
            # to detect. Pass them through, but record that the filter never
            # ran on them.
            logger.warning("Claim entailment response was cut off")
            self._entailment_skipped = True
            return claims
        except JSONParseError:
            logger.warning("Claim entailment response was not valid JSON")
            self._entailment_skipped = True
            return claims

        self._tokens += response.input_tokens + response.output_tokens

        outcome = apply_entailment_results(claims, payload)
        if outcome is None:
            logger.warning("Claim entailment response failed validation")
            self._entailment_skipped = True
            return claims
        self._discarded_claims = list(outcome.discarded)
        return outcome.refined

    def _parse_repairs(
        self,
        raw_repairs: list[dict],
        fetched_by_url: dict[str, ProposedBlob],
    ) -> list[RepairResult]:
        repair_results: list[RepairResult] = []
        for raw_repair in raw_repairs:
            evidence_items = []
            for raw_evidence in raw_repair.get("new_evidence", []):
                source_url = str(raw_evidence.get("source_url", ""))
                fetched = fetched_by_url.get(source_url)
                if fetched is None:
                    continue
                evidence_items.append(
                    ProposedEvidence(
                        source_url=source_url,
                        excerpt=str(raw_evidence.get("excerpt", "")),
                        raw_ref=fetched.content_hash,
                    )
                )
            action = str(raw_repair.get("action", "fixed"))
            if action not in _REPAIR_ACTIONS:
                action = "fixed"
            new_text = raw_repair.get("new_text")
            repair_results.append(
                RepairResult(
                    claim_id=str(raw_repair.get("claim_id", "")),
                    action=action,
                    new_text=(
                        str(new_text) if new_text is not None else None
                    ),
                    new_evidence=evidence_items,
                )
            )
        return repair_results

    async def _weaken_only(
        self,
        brief: str,
        question_id: str,
        repairs: list[dict],
        effort_config,
    ) -> WorkerResult:
        """AC-a: E_OVERCLAIM-only repairs are salvaged by weakening the
        claim text to evidence level. No search/fetch call is made -
        `self._search`/`self.fetch_fn` are never invoked in this branch."""
        config = settings.config.deep_analysis
        repair_lines = "\n".join(
            f"- claim_id={r.get('claim_id', '')} | "
            f"detail={r.get('detail', '')}"
            for r in repairs
        )
        prompt = (
            brief.replace(
                "{fetched_evidence}",
                "(약화 전용 모드 - 재조사 생략)",
            )
            + "\n\n[REPAIR MODE - WEAKEN ONLY]\n"
            "아래 클레임은 과잉주장(E_OVERCLAIM)으로 반려되었다. "
            "재조사하지 말고 문구를 증거 수준으로 약화한 new_text만 "
            "생성하라. 근거가 지지하는 날짜·집단·조건·수치 범위를 유지하라. "
            "상관 근거에는 인과 표현을 쓰지 말고, 지지되지 않는 비교를 "
            "제거하라. 근거 수준으로 약화할 수 없으면 action=abandoned로 "
            "반환하라. JSON 객체 하나만 출력:\n"
            '{"repairs": [{"claim_id": "...", "action": '
            '"weakened|abandoned", "new_text": "약화된 문구"}]}'
            f"\n\n수리 대상:\n{repair_lines}"
        )

        data, response = await call_json(
            self._model,
            prompt,
            max_tokens=min(
                effort_config.token_cap,
                config.worker_max_output_tokens,
            ),
            client=self.llm_client,
            cassette=self.cassette,
            stage="worker_repair",
        )
        self._tokens += response.input_tokens + response.output_tokens

        repair_results = []
        for raw in data.get("repairs", []):
            action = str(raw.get("action", "weakened"))
            if action not in _REPAIR_ACTIONS:
                action = "weakened"
            new_text = raw.get("new_text")
            repair_results.append(
                RepairResult(
                    claim_id=str(raw.get("claim_id", "")),
                    action=action,
                    new_text=(
                        str(new_text) if new_text is not None else None
                    ),
                )
            )

        return WorkerResult(
            question_id=question_id,
            status="completed",
            claims=[],
            blobs=[],
            repairs=repair_results,
            tokens_spent=self._tokens,
            model=self._model,
            confidence_clamped_count=sum(
                self._confidence_clamped_by_source_count.values()
            ),
            confidence_clamped_by_source_count=dict(
                self._confidence_clamped_by_source_count
            ),
        )
