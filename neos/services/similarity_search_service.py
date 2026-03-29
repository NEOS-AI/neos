"""
Similarity Search Service

메시지 유사도 검색 및 RAG 서비스
Strategy Pattern을 사용하여 다양한 검색 전략 지원
"""

from typing import Dict, Any, List, Optional, Protocol
from abc import ABC, abstractmethod

from neos.database.connection import db_manager
from neos.utils.embeddings import embedding_manager
from neos.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Strategy Pattern - 검색 전략 인터페이스
# ============================================================================

class SearchStrategy(Protocol):
    """검색 전략 프로토콜"""
    async def search(
        self,
        query: str,
        query_embedding: List[float],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """검색 실행"""
        ...


class BaseSimilaritySearchStrategy(ABC):
    """베이스 유사도 검색 전략"""

    @abstractmethod
    async def search(
        self,
        query: str,
        query_embedding: List[float],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """검색 실행"""
        pass


# ============================================================================
# Concrete Strategies - 구체적인 검색 전략들
# ============================================================================

class ConversationSearchStrategy(BaseSimilaritySearchStrategy):
    """특정 대화 내 검색 전략"""

    async def search(
        self,
        query: str,
        query_embedding: List[float],
        conversation_id: str,
        limit: int = 5,
        exclude_message_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """대화 내 유사 메시지 검색"""

        query_sql = """
        SELECT * FROM find_similar_messages_in_conversation(
            $1::VARCHAR, $2::TEXT, $3::vector, $4::INTEGER, $5::VARCHAR
        )
        """

        rows = await db_manager.fetch_all(
            query_sql,
            conversation_id,
            query,
            query_embedding,
            limit,
            exclude_message_id
        )

        results = []
        for row in rows:
            results.append({
                "message_id": row[0],
                "content": row[1],
                "role": row[2],
                "sequence_number": row[3],
                "similarity_score": float(row[4]),
                "search_type": "conversation"
            })

        return results


class CrossConversationSearchStrategy(BaseSimilaritySearchStrategy):
    """사용자의 모든 대화에서 검색하는 전략"""

    async def search(
        self,
        query: str,
        query_embedding: List[float],
        user_id: str,
        limit: int = 10,
        similarity_threshold: float = 0.75,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """모든 대화에서 유사 메시지 검색"""

        query_sql = """
        SELECT * FROM find_similar_messages_across_conversations(
            $1::VARCHAR, $2::vector, $3::INTEGER, $4::FLOAT
        )
        """

        rows = await db_manager.fetch_all(
            query_sql,
            user_id,
            query_embedding,
            limit,
            similarity_threshold
        )

        results = []
        for row in rows:
            results.append({
                "message_id": row[0],
                "conversation_id": row[1],
                "conversation_title": row[2],
                "content": row[3],
                "role": row[4],
                "similarity_score": float(row[5]),
                "created_at": row[6],
                "search_type": "cross_conversation"
            })

        return results


class HybridSearchStrategy(BaseSimilaritySearchStrategy):
    """하이브리드 검색 전략 (텍스트 + 벡터)"""

    async def search(
        self,
        query: str,
        query_embedding: List[float],
        user_id: str,
        limit: int = 10,
        text_weight: float = 0.3,
        vector_weight: float = 0.7,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """텍스트 + 벡터 하이브리드 검색"""

        query_sql = """
        SELECT * FROM hybrid_search_messages(
            $1::VARCHAR, $2::TEXT, $3::vector, $4::INTEGER, $5::FLOAT, $6::FLOAT
        )
        """

        rows = await db_manager.fetch_all(
            query_sql,
            user_id,
            query,
            query_embedding,
            limit,
            text_weight,
            vector_weight
        )

        results = []
        for row in rows:
            results.append({
                "message_id": row[0],
                "conversation_id": row[1],
                "content": row[2],
                "role": row[3],
                "text_score": float(row[4]),
                "vector_score": float(row[5]),
                "combined_score": float(row[6]),
                "created_at": row[7],
                "search_type": "hybrid"
            })

        return results


class KnowledgeHybridSearchStrategy(BaseSimilaritySearchStrategy):
    """캐시된 쿼리 결과 대상 하이브리드 전략 (BM25 + Dense Vector, RRF 기반)

    query_cache 테이블에 축적된 검색 결과를 BM25(tsvector)와
    dense vector(pgvector)를 RRF(Reciprocal Rank Fusion)로 결합하여 검색합니다.

    사용 시점: smart_cache miss 후 "이전에 비슷한 질문을 한 적이 있는지"
    query_cache에서 유사 결과를 찾을 때 사용합니다.

    Note: "knowledge" 이름은 Phase 2.8 (Advanced Chunking)에서
    knowledge_documents 전용 테이블로 전환할 때의 확장성을 위해 유지.
    현재는 query_cache 테이블을 대상으로 하며, "cache_hybrid" 별칭으로도 접근 가능.
    """

    async def search(
        self,
        query: str,
        query_embedding: List[float],
        alpha: float = 0.5,
        top_n: int = 50,
        limit: int = 10,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """BM25 + Dense Vector Hybrid Search with RRF

        Args:
            query: 검색 쿼리
            query_embedding: 쿼리 임베딩 벡터
            alpha: 0=pure keyword, 1=pure semantic (기본 0.5)
            top_n: RRF 후보 개수
            limit: 최종 반환 개수
        """
        from neos.config.settings import settings

        alpha = kwargs.get("alpha", getattr(settings, "HYBRID_SEARCH_ALPHA", alpha))
        top_n = kwargs.get("top_n", getattr(settings, "HYBRID_SEARCH_CANDIDATE_COUNT", top_n))

        query_sql = """
        SELECT * FROM knowledge_hybrid_search_rrf(
            $1::TEXT, $2::vector, $3::FLOAT, $4::INT
        )
        LIMIT $5
        """

        rows = await db_manager.fetch_all(
            query_sql,
            query,
            query_embedding,
            alpha,
            top_n,
            limit,
        )

        results = []
        for row in rows:
            results.append({
                "cache_id": row[0],
                "query_text": row[1],
                "response_data": row[2],
                "rrf_score": float(row[3]),
                "bm25_rank": row[4],
                "vector_rank": row[5],
                "search_type": "knowledge_hybrid_rrf",
            })

        return results


# ============================================================================
# DocumentChunkContextualSearchStrategy
# Contextual BM25 + Vector + RRF 하이브리드 검색 (Phase 2)
# ============================================================================

# Contextual Hybrid Search SQL (Vector + BM25 + Reciprocal Rank Fusion)
_CONTEXTUAL_HYBRID_SEARCH_SQL = """
WITH vector_results AS (
    SELECT
        dc.id,
        dc.chunk_text,
        dc.contextual_text,
        dc.document_id,
        dc.chunk_index,
        ROW_NUMBER() OVER (ORDER BY dc.embedding <=> $1::vector) AS vector_rank
    FROM document_chunks dc
    WHERE dc.document_id = ANY($3::INTEGER[])
      AND dc.embedding IS NOT NULL
    ORDER BY dc.embedding <=> $1::vector
    LIMIT 50
),
bm25_results AS (
    SELECT
        dc.id,
        dc.chunk_text,
        dc.contextual_text,
        dc.document_id,
        dc.chunk_index,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(
                dc.contextual_search_vector,
                websearch_to_tsquery('english', $2)
            ) DESC
        ) AS bm25_rank
    FROM document_chunks dc
    WHERE dc.document_id = ANY($3::INTEGER[])
      AND dc.contextual_search_vector @@ websearch_to_tsquery('english', $2)
    LIMIT 50
),
combined AS (
    SELECT
        COALESCE(v.id, b.id) AS id,
        COALESCE(v.chunk_text, b.chunk_text) AS chunk_text,
        COALESCE(v.contextual_text, b.contextual_text) AS contextual_text,
        COALESCE(v.document_id, b.document_id) AS document_id,
        COALESCE(v.chunk_index, b.chunk_index) AS chunk_index,
        COALESCE(1.0 / (60 + v.vector_rank), 0) AS vector_rrf,
        COALESCE(1.0 / (60 + b.bm25_rank), 0) AS bm25_rrf
    FROM vector_results v
    FULL OUTER JOIN bm25_results b ON v.id = b.id
)
SELECT
    id, chunk_text, contextual_text, document_id, chunk_index,
    vector_rrf + bm25_rrf AS combined_score
FROM combined
ORDER BY combined_score DESC
LIMIT $4
"""


class DocumentChunkContextualSearchStrategy(BaseSimilaritySearchStrategy):
    """
    document_chunks 대상 Contextual Hybrid Search (BM25 + Vector + RRF)

    contextual_search_vector(BM25)와 embedding(Vector)을 RRF로 결합.
    contextual_text가 없는 청크는 chunk_text 기반 tsvector로 검색.
    Migration 020 적용 후 사용 가능.
    """

    async def search(
        self,
        query: str,
        query_embedding: List[float],
        document_ids: List[int],
        top_k: int = 10,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Args:
            query: 검색 쿼리 텍스트
            query_embedding: 쿼리 임베딩 벡터 (1536차원)
            document_ids: 검색 대상 문서 ID (사용자 권한 필터링 필수)
            top_k: 반환할 최대 결과 수
        """
        if not document_ids:
            return []

        rows = await db_manager.fetch_all(
            _CONTEXTUAL_HYBRID_SEARCH_SQL,
            query_embedding,
            query,
            document_ids,
            top_k,
        )

        results = []
        for row in rows:
            results.append({
                "chunk_id": row[0],
                "chunk_text": row[1],
                "contextual_text": row[2],
                "document_id": row[3],
                "chunk_index": row[4],
                "combined_score": float(row[5]),
                "search_type": "contextual_hybrid_rrf",
            })

        return results


# ============================================================================
# Main Service - Context (Strategy Pattern)
# ============================================================================

class SimilaritySearchService:
    """
    유사도 검색 서비스

    Strategy Pattern을 사용하여 다양한 검색 전략을 지원
    """

    def __init__(self):
        # 사용 가능한 검색 전략들
        _knowledge_hybrid = KnowledgeHybridSearchStrategy()
        self.strategies = {
            "conversation": ConversationSearchStrategy(),
            "cross_conversation": CrossConversationSearchStrategy(),
            "hybrid": HybridSearchStrategy(),
            "knowledge_hybrid": _knowledge_hybrid,
            "cache_hybrid": _knowledge_hybrid,  # 별칭: query_cache 대상임을 명확히
            "document_chunk_contextual": DocumentChunkContextualSearchStrategy(),  # Phase 2: Contextual Hybrid BM25+Vector
        }
        self.default_strategy = "conversation"

        # Phase 3.1: KG-Augmented Search (lazy init — DB 테이블 필요)
        try:
            from neos.services.kg_search_strategy import KGAugmentedSearchStrategy
            self.strategies["kg_augmented"] = KGAugmentedSearchStrategy()
        except Exception:
            pass  # KG 테이블이 없어도 서비스 시작에 영향 없음

    async def search(
        self,
        query: str,
        strategy: str = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        유사도 검색 실행

        Args:
            query: 검색 쿼리
            strategy: 검색 전략 ("conversation", "cross_conversation", "hybrid")
            **kwargs: 전략별 추가 파라미터

        Returns:
            검색 결과 리스트
        """
        # 전략 선택
        strategy_name = strategy or self.default_strategy
        search_strategy = self.strategies.get(strategy_name)

        if not search_strategy:
            raise ValueError(f"Unknown search strategy: {strategy_name}")

        # 쿼리 임베딩 생성
        query_embedding = await embedding_manager.get_embedding(query, use_cache=True)

        if not query_embedding:
            logger.error("Failed to generate query embedding")
            return []

        # 검색 실행
        try:
            results = await search_strategy.search(
                query=query,
                query_embedding=query_embedding,
                **kwargs
            )

            logger.info(
                f"Similarity search completed: strategy={strategy_name}, "
                f"results={len(results)}"
            )

            return results

        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []

    async def find_similar_in_conversation(
        self,
        conversation_id: str,
        query: str,
        limit: int = 5,
        exclude_message_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """대화 내 유사 메시지 검색 (편의 메서드)"""
        return await self.search(
            query=query,
            strategy="conversation",
            conversation_id=conversation_id,
            limit=limit,
            exclude_message_id=exclude_message_id
        )

    async def find_similar_across_conversations(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        similarity_threshold: float = 0.75
    ) -> List[Dict[str, Any]]:
        """모든 대화에서 유사 메시지 검색 (편의 메서드)"""
        return await self.search(
            query=query,
            strategy="cross_conversation",
            user_id=user_id,
            limit=limit,
            similarity_threshold=similarity_threshold
        )

    async def hybrid_search(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        text_weight: float = 0.3,
        vector_weight: float = 0.7
    ) -> List[Dict[str, Any]]:
        """하이브리드 검색 (편의 메서드)"""
        return await self.search(
            query=query,
            strategy="hybrid",
            user_id=user_id,
            limit=limit,
            text_weight=text_weight,
            vector_weight=vector_weight
        )

    async def knowledge_hybrid_search_with_rerank(
        self,
        query: str,
        top_candidates: int = 50,
        final_top_n: int = 10,
    ) -> List[Dict[str, Any]]:
        """지식 하이브리드 검색 + cross-encoder re-ranking (편의 메서드)

        1단계: BM25+Dense RRF로 top_candidates 검색
        2단계: Cohere cross-encoder로 re-rank하여 final_top_n 반환
        """
        candidates = await self.search(
            query=query,
            strategy="knowledge_hybrid",
            alpha=settings.HYBRID_SEARCH_ALPHA,
            top_n=top_candidates,
            limit=top_candidates,
        )

        if not candidates:
            return []

        from neos.services.reranker import reranker_service
        return await reranker_service.rerank_results(
            query, candidates, top_n=final_top_n
        )

    async def get_rag_context(
        self,
        conversation_id: str,
        query: str,
        top_k: int = 3,
        include_cross_conversation: bool = False,
        user_id: Optional[str] = None,
        similarity_threshold: float = 0.75
    ) -> Dict[str, Any]:
        """
        RAG를 위한 컨텍스트 생성

        Args:
            conversation_id: 현재 대화 ID
            query: 사용자 쿼리
            top_k: 가져올 유사 메시지 수
            include_cross_conversation: 다른 대화에서도 검색할지 여부
            user_id: 사용자 ID (cross_conversation 사용 시 필요)
            similarity_threshold: 유사도 임계값 (크로스 대화 검색에 적용)

        Returns:
            {
                "query": str,
                "relevant_messages": [...],
                "context_text": str
            }
        """
        relevant_messages = []

        # 현재 대화에서 검색
        conv_results = await self.find_similar_in_conversation(
            conversation_id=conversation_id,
            query=query,
            limit=top_k
        )
        relevant_messages.extend(conv_results)

        # 다른 대화에서도 검색 (옵션)
        if include_cross_conversation and user_id:
            cross_results = await self.find_similar_across_conversations(
                user_id=user_id,
                query=query,
                limit=top_k,
                similarity_threshold=similarity_threshold
            )
            # 중복 제거
            existing_ids = {msg["message_id"] for msg in relevant_messages}
            for result in cross_results:
                if result["message_id"] not in existing_ids:
                    relevant_messages.append(result)

        # 점수 순으로 정렬하고 top_k개만 유지
        relevant_messages.sort(
            key=lambda x: x.get("similarity_score", x.get("combined_score", 0)),
            reverse=True
        )
        relevant_messages = relevant_messages[:top_k]

        # 컨텍스트 텍스트 생성
        context_parts = []
        for i, msg in enumerate(relevant_messages, 1):
            context_parts.append(
                f"[관련 메시지 {i}] (유사도: {msg.get('similarity_score', 0):.2f})\n"
                f"{msg['content']}\n"
            )

        context_text = "\n".join(context_parts) if context_parts else ""

        return {
            "query": query,
            "relevant_messages": relevant_messages,
            "context_text": context_text,
            "total_relevant": len(relevant_messages)
        }


# 전역 인스턴스
similarity_search_service = SimilaritySearchService()
