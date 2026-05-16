"""
Hybrid Search Engine - 벡터 + BM25 + RRF 하이브리드 검색

단일 SQL CTE 쿼리로 pgvector 코사인 유사도와 PostgreSQL full-text search를
동시에 수행하고, Reciprocal Rank Fusion으로 결과를 병합한다.
"""

import logging
from typing import List, Optional

from sqlalchemy import text

from neos.database.connection import get_session_ctx
from neos.utils.embeddings import EmbeddingManager
from .tool_metadata import ToolDefinition, ToolSearchResult

logger = logging.getLogger(__name__)

# 하이브리드 검색 SQL (벡터 + BM25 + RRF 병합)
HYBRID_SEARCH_SQL = """
WITH vector_results AS (
    SELECT id, name, display_name, description, schema, category, tags, source_type,
           1 - (embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)) AS vector_score,
           ROW_NUMBER() OVER (ORDER BY embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)) AS vector_rank
    FROM tool_registry
    WHERE is_active = TRUE AND defer_loading = TRUE
      AND embedding IS NOT NULL
      AND (:category IS NULL OR category = :category)
    ORDER BY embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)
    LIMIT 20
),
bm25_results AS (
    SELECT id, name, display_name, description, schema, category, tags, source_type,
           ts_rank_cd(search_vector, websearch_to_tsquery('english', :query)) AS bm25_score,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', :query)) DESC
           ) AS bm25_rank
    FROM tool_registry
    WHERE is_active = TRUE AND defer_loading = TRUE
      AND search_vector @@ websearch_to_tsquery('english', :query)
      AND (:category IS NULL OR category = :category)
    ORDER BY bm25_score DESC
    LIMIT 20
),
combined AS (
    SELECT
        COALESCE(v.id, b.id) AS id,
        COALESCE(v.name, b.name) AS name,
        COALESCE(v.display_name, b.display_name) AS display_name,
        COALESCE(v.description, b.description) AS description,
        COALESCE(v.schema, b.schema) AS schema,
        COALESCE(v.category, b.category) AS category,
        COALESCE(v.tags, b.tags) AS tags,
        COALESCE(v.source_type, b.source_type) AS source_type,
        COALESCE(1.0 / (:rrf_k + v.vector_rank), 0) AS vector_rrf,
        COALESCE(1.0 / (:rrf_k + b.bm25_rank), 0) AS bm25_rrf,
        CASE
            WHEN v.id IS NOT NULL AND b.id IS NOT NULL THEN 'hybrid'
            WHEN v.id IS NOT NULL THEN 'vector'
            ELSE 'bm25'
        END AS match_source
    FROM vector_results v
    FULL OUTER JOIN bm25_results b ON v.id = b.id
)
SELECT
    name, display_name, description, schema, category, tags, source_type,
    vector_rrf + bm25_rrf AS combined_score,
    match_source
FROM combined
ORDER BY combined_score DESC
LIMIT :top_k;
"""

# 벡터 전용 검색 SQL (BM25 폴백 불가 시)
VECTOR_ONLY_SQL = """
SELECT name, display_name, description, schema, category, tags, source_type,
       1 - (embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)) AS combined_score,
       'vector' AS match_source
FROM tool_registry
WHERE is_active = TRUE AND defer_loading = TRUE
  AND embedding IS NOT NULL
  AND (:category IS NULL OR category = :category)
ORDER BY embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)
LIMIT :top_k;
"""

# BM25 전용 검색 SQL (임베딩 실패 시)
BM25_ONLY_SQL = """
SELECT name, display_name, description, schema, category, tags, source_type,
       ts_rank_cd(search_vector, websearch_to_tsquery('english', :query)) AS combined_score,
       'bm25' AS match_source
FROM tool_registry
WHERE is_active = TRUE AND defer_loading = TRUE
  AND search_vector @@ websearch_to_tsquery('english', :query)
  AND (:category IS NULL OR category = :category)
ORDER BY combined_score DESC
LIMIT :top_k;
"""


class HybridSearchEngine:
    """벡터 + BM25 하이브리드 검색 엔진"""

    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        rrf_k: int = 60,
    ):
        self.embedding_manager = embedding_manager
        self.rrf_k = rrf_k

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> List[ToolSearchResult]:
        """
        하이브리드 검색 수행

        1. 쿼리 임베딩 생성
        2. 단일 SQL로 벡터 + BM25 동시 검색
        3. RRF로 결과 병합
        4. 상위 top_k 반환

        임베딩 실패 시 BM25 only, BM25 매치 없음 시 vector only로 폴백.
        """
        # 1. 쿼리 임베딩 생성
        query_embedding = await self.embedding_manager.get_embedding(query)

        if query_embedding is None:
            logger.warning(f"Embedding generation failed for query: '{query}', falling back to BM25-only")
            return await self._search_bm25_only(query, top_k, category)

        # 2. 하이브리드 검색 실행
        results = await self._search_hybrid(query, query_embedding, top_k, category)

        # 3. 하이브리드 결과가 없으면 vector-only 폴백
        if not results:
            logger.info(f"No hybrid results for '{query}', trying vector-only")
            results = await self._search_vector_only(query_embedding, top_k, category)

        return results

    async def _search_hybrid(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int,
        category: Optional[str],
    ) -> List[ToolSearchResult]:
        """하이브리드 검색 (벡터 + BM25 + RRF)"""
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        async with get_session_ctx() as session:
            result = await session.execute(
                text(HYBRID_SEARCH_SQL),
                {
                    "query": query,
                    "query_embedding": embedding_str,
                    "category": category,
                    "rrf_k": self.rrf_k,
                    "top_k": top_k,
                }
            )
            rows = result.fetchall()

        return [self._row_to_result(row) for row in rows]

    async def _search_vector_only(
        self,
        query_embedding: List[float],
        top_k: int,
        category: Optional[str],
    ) -> List[ToolSearchResult]:
        """벡터 전용 검색"""
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        async with get_session_ctx() as session:
            result = await session.execute(
                text(VECTOR_ONLY_SQL),
                {
                    "query_embedding": embedding_str,
                    "category": category,
                    "top_k": top_k,
                }
            )
            rows = result.fetchall()

        return [self._row_to_result(row) for row in rows]

    async def _search_bm25_only(
        self,
        query: str,
        top_k: int,
        category: Optional[str],
    ) -> List[ToolSearchResult]:
        """BM25 전용 검색 (임베딩 실패 시 폴백)"""
        async with get_session_ctx() as session:
            result = await session.execute(
                text(BM25_ONLY_SQL),
                {
                    "query": query,
                    "category": category,
                    "top_k": top_k,
                }
            )
            rows = result.fetchall()

        return [self._row_to_result(row) for row in rows]

    @staticmethod
    def _row_to_result(row) -> ToolSearchResult:
        """DB row를 ToolSearchResult로 변환"""
        return ToolSearchResult(
            tool=ToolDefinition(
                name=row.name,
                description=row.description,
                input_schema=row.schema or {},
                source_type=row.source_type,
                category=row.category or "general",
                tags=row.tags or [],
            ),
            score=float(row.combined_score),
            match_source=row.match_source,
        )
