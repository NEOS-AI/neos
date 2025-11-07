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
        self.strategies = {
            "conversation": ConversationSearchStrategy(),
            "cross_conversation": CrossConversationSearchStrategy(),
            "hybrid": HybridSearchStrategy()
        }
        self.default_strategy = "conversation"

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

    async def get_rag_context(
        self,
        conversation_id: str,
        query: str,
        top_k: int = 3,
        include_cross_conversation: bool = False,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        RAG를 위한 컨텍스트 생성

        Args:
            conversation_id: 현재 대화 ID
            query: 사용자 쿼리
            top_k: 가져올 유사 메시지 수
            include_cross_conversation: 다른 대화에서도 검색할지 여부
            user_id: 사용자 ID (cross_conversation 사용 시 필요)

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
                similarity_threshold=0.8
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
