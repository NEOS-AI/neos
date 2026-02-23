"""
Knowledge Graph Augmented Search Strategy (Phase 3.1)

쿼리에서 엔티티 추출 → KG 탐색 → 확장 컨텍스트로 하이브리드 검색 → 엔티티 관련성 re-rank
"""

from typing import Dict, Any, List, Optional
import logging
import json

from neos.services.similarity_search_service import BaseSimilaritySearchStrategy
from neos.database.connection import db_manager
from neos.utils.embeddings import embedding_manager
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class KGAugmentedSearchStrategy(BaseSimilaritySearchStrategy):
    """Knowledge Graph 보강 검색 전략

    1. 쿼리에서 엔티티 추출 (LLM)
    2. DB에서 관련 엔티티 KG 탐색 (max depth=2)
    3. 관련 엔티티로 쿼리 확장
    4. 확장 쿼리로 하이브리드 검색
    5. 엔티티 관련성으로 결과 re-rank
    """

    def __init__(self):
        self.max_kg_depth = getattr(settings, "KG_MAX_TRAVERSAL_DEPTH", 2)
        self.max_related_entities = 10
        self.kg_weight = getattr(settings, "KG_SEARCH_WEIGHT", 0.3)

    async def search(
        self,
        query: str,
        query_embedding: List[float],
        limit: int = 10,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """KG 보강 검색 실행"""

        # Step 1: 쿼리에서 엔티티 추출
        query_entities = await self._extract_query_entities(query)

        if not query_entities:
            logger.debug("[KGSearch] 쿼리에서 엔티티 미발견, 표준 검색으로 fallback")
            return await self._fallback_search(query, query_embedding, limit)

        logger.info(f"[KGSearch] 쿼리 엔티티 {len(query_entities)}개 발견")

        # Step 2: KG 탐색으로 관련 엔티티 검색
        related_entities = await self._traverse_knowledge_graph(query_entities)
        logger.info(f"[KGSearch] 관련 엔티티 {len(related_entities)}개 발견")

        # Step 3: 쿼리 확장
        expanded_query = self._build_expanded_query(query, query_entities, related_entities)
        expanded_embedding = await embedding_manager.get_embedding(expanded_query)
        if not expanded_embedding:
            expanded_embedding = query_embedding

        # Step 4: 하이브리드 검색
        from neos.services.similarity_search_service import KnowledgeHybridSearchStrategy
        base_strategy = KnowledgeHybridSearchStrategy()
        search_results = await base_strategy.search(
            query=expanded_query,
            query_embedding=expanded_embedding,
            alpha=0.6,
            top_n=limit * 2,
            limit=limit * 2,
        )

        # Step 5: 엔티티 관련성 re-rank
        ranked_results = self._rerank_with_entity_relevance(
            search_results, query_entities, related_entities
        )

        return ranked_results[:limit]

    async def _extract_query_entities(self, query: str) -> List[Dict[str, Any]]:
        """쿼리에서 엔티티 추출 — DB의 기존 엔티티와 매칭"""
        try:
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                # 쿼리 텍스트에서 기존 KG 엔티티와 이름 매칭
                rows = await conn.fetch("""
                    SELECT entity_id, entity_name, entity_type, confidence_score
                    FROM kg_entities
                    WHERE entity_name ILIKE ANY(
                        SELECT '%' || word || '%'
                        FROM unnest(string_to_array($1, ' ')) AS word
                        WHERE length(word) > 3
                    )
                    AND confidence_score >= $2
                    ORDER BY confidence_score DESC
                    LIMIT 10
                """, query, getattr(settings, "KG_MIN_CONFIDENCE", 0.7))

                return [
                    {
                        "entity_id": row["entity_id"],
                        "entity_name": row["entity_name"],
                        "entity_type": row["entity_type"],
                        "confidence": row["confidence_score"],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"[KGSearch] 엔티티 추출 실패: {e}")
            return []

    async def _traverse_knowledge_graph(
        self, start_entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """KG 탐색으로 관련 엔티티 검색"""
        all_related = []

        try:
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                for entity in start_entities[:5]:
                    rows = await conn.fetch("""
                        SELECT * FROM kg_traverse_neighbors($1, $2, NULL)
                    """, entity["entity_id"], self.max_kg_depth)

                    for row in rows:
                        if row["depth"] > 0:  # 시작 엔티티 제외
                            all_related.append({
                                "entity_id": row["entity_id"],
                                "entity_name": row["entity_name"],
                                "entity_type": row["entity_type"],
                                "depth": row["depth"],
                            })

        except Exception as e:
            logger.warning(f"[KGSearch] KG 탐색 실패: {e}")
            return []

        # 중복 제거 후 depth 순 정렬
        unique = {e["entity_id"]: e for e in all_related}
        sorted_entities = sorted(unique.values(), key=lambda x: x["depth"])
        return sorted_entities[:self.max_related_entities]

    def _build_expanded_query(
        self,
        original_query: str,
        query_entities: List[Dict[str, Any]],
        related_entities: List[Dict[str, Any]],
    ) -> str:
        """엔티티 컨텍스트로 쿼리 확장"""
        entity_names = [e["entity_name"] for e in query_entities]
        related_names = [e["entity_name"] for e in related_entities[:5]]

        expanded = original_query
        if entity_names:
            expanded += f"\n\nRelevant entities: {', '.join(entity_names)}"
        if related_names:
            expanded += f"\nRelated concepts: {', '.join(related_names)}"

        return expanded

    def _rerank_with_entity_relevance(
        self,
        results: List[Dict[str, Any]],
        query_entities: List[Dict[str, Any]],
        related_entities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """엔티티 관련성으로 결과 re-rank"""
        query_names = {e["entity_name"].lower() for e in query_entities}
        related_names = {e["entity_name"].lower() for e in related_entities}

        for result in results:
            result_text = (result.get("query_text") or result.get("content") or "").lower()

            query_matches = sum(1 for name in query_names if name in result_text)
            related_matches = sum(1 for name in related_names if name in result_text)

            entity_boost = (
                query_matches * 1.0 + related_matches * 0.5
            ) / max(len(query_names), 1)

            original_score = result.get("rrf_score") or result.get("similarity") or 0.0
            result["final_score"] = (
                (1 - self.kg_weight) * original_score + self.kg_weight * entity_boost
            )

        results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        return results

    async def _fallback_search(
        self,
        query: str,
        query_embedding: List[float],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """KG 없을 때 표준 하이브리드 검색으로 fallback"""
        from neos.services.similarity_search_service import KnowledgeHybridSearchStrategy
        strategy = KnowledgeHybridSearchStrategy()
        return await strategy.search(
            query=query, query_embedding=query_embedding, limit=limit
        )
