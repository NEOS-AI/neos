"""
Cross-Encoder Re-Ranking Service

초기 검색(top-50) 후 cross-encoder로 re-rank하여 top-10을 반환합니다.
Cohere Rerank API로 시작하여 GPU 없이 빠르게 도입 가능합니다.

Graceful degradation: Cohere 미설치/미설정 시 원본 순서를 유지합니다.
"""

import logging
from typing import List, Dict, Any

from neos.config.settings import settings

logger = logging.getLogger(__name__)


class CohereReranker:
    """Cohere Rerank API 래퍼"""

    def __init__(self):
        self._client = None
        self._available = None

    def _get_client(self):
        """Lazy-init Cohere client"""
        if self._available is False:
            return None
        if self._client is None:
            try:
                import cohere
                api_key = getattr(settings, "COHERE_API_KEY", None)
                if not api_key:
                    logger.warning("[Reranker] COHERE_API_KEY not configured, reranking disabled")
                    self._available = False
                    return None
                self._client = cohere.AsyncClientV2(api_key=api_key)
                self._available = True
            except ImportError:
                logger.warning("[Reranker] cohere package not installed, reranking disabled")
                self._available = False
                return None
        return self._client

    async def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: int = 10,
        model: str = None,
    ) -> List[Dict[str, Any]]:
        """Cohere Rerank API로 문서를 re-rank합니다.

        Args:
            query: 원본 검색 쿼리
            documents: 문서 리스트 (각 항목에 "content" 또는 "query_text" 키 필요)
            top_n: 반환할 문서 수
            model: Cohere 모델 이름

        Returns:
            re-rank된 문서 리스트 (rerank_score 필드 추가)
        """
        client = self._get_client()
        if client is None:
            logger.debug("[Reranker] Cohere unavailable, returning original order")
            return documents[:top_n]

        model = model or getattr(settings, "RERANKER_MODEL", "rerank-english-v3.0")

        try:
            # 문서 텍스트 추출 — contextual_text 우선 사용 (Contextual Retrieval 지원)
            texts = []
            for d in documents:
                text = (
                    d.get("contextual_text")
                    or d.get("content")
                    or d.get("query_text")
                    or d.get("title")
                    or ""
                )
                texts.append(text[:4096])  # Cohere max input per document

            if not texts:
                return documents[:top_n]

            response = await client.rerank(
                model=model,
                query=query,
                documents=texts,
                top_n=min(top_n, len(texts)),
            )

            reranked = []
            for result in response.results:
                doc = documents[result.index].copy()
                doc["rerank_score"] = result.relevance_score
                reranked.append(doc)

            logger.info(
                f"[Reranker] Re-ranked {len(documents)} docs → top {len(reranked)} "
                f"(top score: {reranked[0]['rerank_score']:.3f})"
            )
            return reranked

        except Exception as e:
            logger.error(f"[Reranker] Cohere rerank failed: {e}, returning original order")
            return documents[:top_n]


class RerankerService:
    """Re-ranking 서비스 파사드

    RERANKER_ENABLED 설정에 따라 re-ranking을 적용합니다.
    """

    def __init__(self):
        self._reranker = CohereReranker()

    async def rerank_results(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int = None,
    ) -> List[Dict[str, Any]]:
        """검색 결과를 re-rank합니다.

        Args:
            query: 원본 쿼리
            candidates: 초기 검색 결과 (top-50 등)
            top_n: 최종 반환 개수

        Returns:
            re-rank된 결과 리스트
        """
        if not getattr(settings, "RERANKER_ENABLED", True):
            return candidates[:top_n or 10]

        top_n = top_n or getattr(settings, "RERANKER_TOP_N", 10)
        return await self._reranker.rerank(query, candidates, top_n=top_n)


# 싱글톤 인스턴스
reranker_service = RerankerService()
