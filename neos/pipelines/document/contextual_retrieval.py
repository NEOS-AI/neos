"""
Contextual Retrieval - 청크별 문서 컨텍스트 자동 생성

Anthropic의 Contextual Retrieval 기법 구현:
- 각 청크에 전체 문서 컨텍스트를 요약하는 1-2문장 생성
- Anthropic Prompt Caching (ephemeral)으로 비용 절감 (90% 절감 기대)
- 비동기 세마포어 기반 병렬 처리
- CONTEXTUAL_MAX_CHUNKS_PER_DOC / CONTEXTUAL_BUDGET_CAP_USD 기반 비용 통제

참조: https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import anthropic

from neos.config.settings import settings
from neos.pipelines.document.chunker import DocumentChunk

logger = logging.getLogger(__name__)

# Haiku 4.5 가격 (USD per token)
_HAIKU_INPUT_PRICE = 0.80 / 1_000_000
_HAIKU_CACHE_WRITE_PRICE = 1.00 / 1_000_000
_HAIKU_CACHE_READ_PRICE = 0.08 / 1_000_000
_HAIKU_OUTPUT_PRICE = 4.00 / 1_000_000


@dataclass
class ContextualChunk:
    """컨텍스트가 보강된 청크"""

    original_chunk: DocumentChunk
    contextual_text: str           # context_snippet + "\n\n" + chunk_text (임베딩 대상)
    context_snippet: str           # 생성된 컨텍스트 설명 (저장/디버깅용)
    cache_hit: bool = False
    tokens_used: int = 0
    cost_usd: float = 0.0


def _make_fallback_chunk(chunk: DocumentChunk) -> ContextualChunk:
    """API 실패 또는 비용 초과 시 원본 텍스트로 fallback"""
    return ContextualChunk(
        original_chunk=chunk,
        contextual_text=chunk.chunk_text,
        context_snippet="",
        cache_hit=False,
        tokens_used=0,
        cost_usd=0.0,
    )


class ContextualRetrieval:
    """
    Anthropic Contextual Retrieval 구현체

    한 문서의 모든 청크를 처리할 때 전체 문서를 ephemeral 캐시에 올려놓고
    각 청크에 대해 짧은 컨텍스트를 생성한다. 첫 번째 청크 이후로는
    캐시 히트가 발생하여 문서 토큰 비용이 90% 절감된다.

    비용 통제:
    - CONTEXTUAL_MAX_CHUNKS_PER_DOC: 앞 N개 청크만 처리, 나머지 fallback
    - CONTEXTUAL_BUDGET_CAP_USD: 누적 비용 초과 시 이후 청크 fallback
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_context_tokens: int = 200,
        max_concurrent: int = 3,
        max_chunks_per_doc: Optional[int] = None,
        budget_cap_usd: Optional[float] = None,
    ):
        self.model = model or settings.CONTEXTUAL_MODEL
        self.max_context_tokens = max_context_tokens
        self.max_concurrent = max_concurrent
        self.max_chunks_per_doc = max_chunks_per_doc or settings.CONTEXTUAL_MAX_CHUNKS_PER_DOC
        self.budget_cap_usd = budget_cap_usd if budget_cap_usd is not None else settings.CONTEXTUAL_BUDGET_CAP_USD

        # anthropic SDK 직접 사용 (LLMFactory는 cache_control content block 미지원)
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate_contexts(
        self,
        full_document: str,
        chunks: List[DocumentChunk],
    ) -> List[ContextualChunk]:
        """
        문서 전체와 청크 리스트를 받아 컨텍스트가 보강된 청크 리스트 반환.

        Anthropic Prompt Caching 활용:
        - full_document에 ephemeral cache_control 적용
        - 첫 번째 청크에서 캐시 미스 (full price)
        - 이후 청크들에서 캐시 히트 (90% 절감)

        비용 통제:
        - max_chunks_per_doc 초과분은 즉시 fallback (처리 전 슬라이싱)
        - budget_cap_usd 초과 시 이후 청크 fallback
        """
        if not chunks:
            return []

        # CONTEXTUAL_MAX_CHUNKS_PER_DOC 적용: 초과분은 처리 전 fallback으로 분리
        if self.max_chunks_per_doc > 0 and len(chunks) > self.max_chunks_per_doc:
            logger.info(
                f"[ContextualRetrieval] 청크 수({len(chunks)}) > max_chunks_per_doc({self.max_chunks_per_doc}), "
                f"앞 {self.max_chunks_per_doc}개만 처리"
            )
            chunks_to_process = chunks[: self.max_chunks_per_doc]
            fallback_chunks = chunks[self.max_chunks_per_doc :]
        else:
            chunks_to_process = chunks
            fallback_chunks = []

        logger.info(
            f"[ContextualRetrieval] 시작: {len(chunks_to_process)}개 청크 처리, "
            f"model={self.model}, max_concurrent={self.max_concurrent}"
        )
        start_time = time.monotonic()

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _generate_single(chunk: DocumentChunk, idx: int) -> ContextualChunk:
            async with semaphore:
                return await self._generate_context_for_chunk(
                    full_document=full_document,
                    chunk=chunk,
                    chunk_index=idx,
                )

        tasks = [
            _generate_single(chunk, idx) for idx, chunk in enumerate(chunks_to_process)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 수집 + 비용 초과 시 이후 fallback
        contextual_chunks: List[ContextualChunk] = []
        total_cost = 0.0
        total_cache_hits = 0
        budget_exceeded = False

        for i, result in enumerate(raw_results):
            if budget_exceeded:
                # 비용 한도 초과 → 이후 청크 모두 fallback
                contextual_chunks.append(_make_fallback_chunk(chunks_to_process[i]))
                continue

            if isinstance(result, Exception):
                logger.warning(
                    f"[ContextualRetrieval] 청크 {i} 실패: {result}. 원본 텍스트로 fallback."
                )
                contextual_chunks.append(_make_fallback_chunk(chunks_to_process[i]))
            else:
                contextual_chunks.append(result)
                total_cost += result.cost_usd
                if result.cache_hit:
                    total_cache_hits += 1

                # 비용 한도 체크
                if self.budget_cap_usd > 0 and total_cost >= self.budget_cap_usd:
                    logger.warning(
                        f"[ContextualRetrieval] 비용 한도 초과: "
                        f"${total_cost:.6f} >= ${self.budget_cap_usd} "
                        f"(처리된 청크: {i + 1}/{len(chunks_to_process)}). "
                        f"이후 청크는 fallback 처리."
                    )
                    budget_exceeded = True

        # max_chunks_per_doc 초과분 fallback 결과 추가
        for chunk in fallback_chunks:
            contextual_chunks.append(_make_fallback_chunk(chunk))

        elapsed = time.monotonic() - start_time
        logger.info(
            f"[ContextualRetrieval] 완료: "
            f"cache_hits={total_cache_hits}/{len(chunks_to_process)}, "
            f"총 비용=${total_cost:.6f}, "
            f"소요={elapsed:.1f}s"
        )

        # Prometheus 지표 기록 (lazy import으로 순환 참조 방지)
        try:
            from neos.observability.metrics import (
                contextual_retrieval_chunks_total,
                contextual_retrieval_cache_hits_total,
                contextual_retrieval_cost_usd_total,
                contextual_retrieval_duration_seconds,
            )
            success_count = sum(
                1 for c in contextual_chunks if c.context_snippet
            )
            fallback_count = sum(
                1 for c in contextual_chunks if not c.context_snippet
            )
            contextual_retrieval_chunks_total.labels(status="success").inc(success_count)
            contextual_retrieval_chunks_total.labels(status="fallback").inc(fallback_count)
            contextual_retrieval_cache_hits_total.inc(total_cache_hits)
            contextual_retrieval_cost_usd_total.inc(total_cost)
            contextual_retrieval_duration_seconds.observe(elapsed)
        except Exception:
            pass  # 메트릭 오류가 파이프라인을 중단시키지 않도록

        return contextual_chunks

    async def _generate_context_for_chunk(
        self,
        full_document: str,
        chunk: DocumentChunk,
        chunk_index: int,
    ) -> ContextualChunk:
        """단일 청크에 대한 컨텍스트 생성 (Anthropic API + prompt caching)"""
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_context_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"<document>\n{full_document}\n</document>\n\n",
                            "cache_control": {"type": "ephemeral"},  # 문서만 캐시
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Here is the chunk we want to situate within the whole document:\n\n"
                                f"<chunk>\n{chunk.chunk_text}\n</chunk>\n\n"
                                f"Please give a short succinct context to situate this chunk "
                                f"within the overall document for the purposes of improving "
                                f"search retrieval of the chunk. "
                                f"Answer only with the succinct context and nothing else."
                            ),
                        },
                    ],
                }
            ],
        )

        context_snippet = response.content[0].text.strip()
        contextual_text = f"{context_snippet}\n\n{chunk.chunk_text}"

        usage = response.usage
        cache_hit = (
            hasattr(usage, "cache_read_input_tokens")
            and (usage.cache_read_input_tokens or 0) > 0
        )

        cost = (
            getattr(usage, "input_tokens", 0) * _HAIKU_INPUT_PRICE
            + getattr(usage, "cache_creation_input_tokens", 0) * _HAIKU_CACHE_WRITE_PRICE
            + getattr(usage, "cache_read_input_tokens", 0) * _HAIKU_CACHE_READ_PRICE
            + getattr(usage, "output_tokens", 0) * _HAIKU_OUTPUT_PRICE
        )

        logger.debug(
            f"[ContextualRetrieval] 청크 {chunk_index}: "
            f"cache_hit={cache_hit}, cost=${cost:.6f}, "
            f"context='{context_snippet[:60]}...'"
        )

        return ContextualChunk(
            original_chunk=chunk,
            contextual_text=contextual_text,
            context_snippet=context_snippet,
            cache_hit=cache_hit,
            tokens_used=(
                getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
            ),
            cost_usd=cost,
        )

    @staticmethod
    def estimate_cost(
        num_chunks: int,
        avg_doc_tokens: int,
        avg_chunk_tokens: int = 300,
        context_tokens: int = 100,
    ) -> dict:
        """
        처리 비용 사전 추정 (Haiku 4.5 기준)

        Returns:
            {without_caching_usd, with_caching_usd, savings_pct, num_chunks, avg_doc_tokens}
        """
        if num_chunks <= 0:
            return {
                "without_caching_usd": 0.0,
                "with_caching_usd": 0.0,
                "savings_pct": 0.0,
                "num_chunks": num_chunks,
                "avg_doc_tokens": avg_doc_tokens,
            }

        without_caching = num_chunks * (
            (avg_doc_tokens + avg_chunk_tokens) * _HAIKU_INPUT_PRICE
            + context_tokens * _HAIKU_OUTPUT_PRICE
        )
        # 첫 청크: 캐시 쓰기 + 나머지: 캐시 읽기
        with_caching = (
            avg_doc_tokens * _HAIKU_CACHE_WRITE_PRICE
            + avg_chunk_tokens * _HAIKU_INPUT_PRICE
            + context_tokens * _HAIKU_OUTPUT_PRICE
        ) + (num_chunks - 1) * (
            avg_doc_tokens * _HAIKU_CACHE_READ_PRICE
            + avg_chunk_tokens * _HAIKU_INPUT_PRICE
            + context_tokens * _HAIKU_OUTPUT_PRICE
        )
        savings_pct = (
            (1 - with_caching / without_caching) * 100 if without_caching > 0 else 0.0
        )

        return {
            "without_caching_usd": round(without_caching, 6),
            "with_caching_usd": round(with_caching, 6),
            "savings_pct": round(savings_pct, 1),
            "num_chunks": num_chunks,
            "avg_doc_tokens": avg_doc_tokens,
        }
