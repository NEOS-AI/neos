"""
Message Embedding Service

메시지 임베딩 생성 및 저장 서비스
"""

from typing import Dict, Any, List, Optional
import json
import asyncio

from neos.database.connection import db_manager
from neos.utils.embeddings import embedding_manager
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class MessageEmbeddingService:
    """메시지 임베딩 서비스"""

    def __init__(self):
        # Embedding manager로부터 provider 정보 가져오기
        self.embedding_provider = embedding_manager.provider_name
        self.embedding_model = embedding_manager.model
        self.dimension = embedding_manager.dimension

    async def create_message_embedding(
        self,
        message_id: str,
        conversation_id: str,
        content: str,
        role: str,
        user_id: Optional[str] = None,
        sequence_number: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        메시지 임베딩 생성 및 저장

        Returns:
            성공 여부
        """
        try:
            # 임베딩 생성
            embedding = await embedding_manager.get_embedding(content, use_cache=True)

            if not embedding:
                logger.error(f"Failed to generate embedding for message {message_id}")
                return False

            # DB에 저장
            query = """
            INSERT INTO message_embeddings (
                message_id,
                conversation_id,
                embedding,
                embedding_model,
                embedding_provider,
                content,
                role,
                sequence_number,
                user_id,
                metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (message_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedding_provider = EXCLUDED.embedding_provider,
                embedding_model = EXCLUDED.embedding_model,
                content = EXCLUDED.content,
                updated_at = CURRENT_TIMESTAMP
            """

            await db_manager.execute(
                query,
                message_id,
                conversation_id,
                embedding,
                self.embedding_model,
                self.embedding_provider,
                content,
                role,
                sequence_number,
                user_id,
                json.dumps(metadata or {})
            )

            logger.info(f"Created embedding for message {message_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create message embedding: {e}")
            return False

    async def batch_create_embeddings(
        self,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        여러 메시지의 임베딩을 배치로 생성

        Args:
            messages: 메시지 리스트 [{"message_id": ..., "content": ..., ...}]

        Returns:
            {message_id: success} 딕셔너리
        """
        results = {}

        # 병렬 처리
        tasks = []
        for msg in messages:
            task = self.create_message_embedding(
                message_id=msg["message_id"],
                conversation_id=msg["conversation_id"],
                content=msg["content"],
                role=msg.get("role", "user"),
                user_id=msg.get("user_id"),
                sequence_number=msg.get("sequence_number"),
                metadata=msg.get("metadata")
            )
            tasks.append((msg["message_id"], task))

        # 실행
        for message_id, task in tasks:
            success = await task
            results[message_id] = success

        return results

    async def get_message_embedding(
        self,
        message_id: str
    ) -> Optional[Dict[str, Any]]:
        """메시지 임베딩 조회"""
        query = """
        SELECT
            message_id,
            conversation_id,
            embedding,
            embedding_model,
            content,
            role,
            sequence_number,
            user_id,
            created_at,
            metadata
        FROM message_embeddings
        WHERE message_id = $1
        """

        row = await db_manager.fetch_one(query, message_id)

        if not row:
            return None

        return {
            "message_id": row[0],
            "conversation_id": row[1],
            "embedding": row[2],
            "embedding_model": row[3],
            "content": row[4],
            "role": row[5],
            "sequence_number": row[6],
            "user_id": row[7],
            "created_at": row[8],
            "metadata": row[9] if row[9] else {}
        }

    async def delete_message_embedding(self, message_id: str) -> bool:
        """메시지 임베딩 삭제"""
        try:
            query = "DELETE FROM message_embeddings WHERE message_id = $1"
            await db_manager.execute(query, message_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete message embedding: {e}")
            return False

    async def get_conversation_embeddings_count(
        self,
        conversation_id: str
    ) -> int:
        """대화의 임베딩 수 조회"""
        query = """
        SELECT COUNT(*) FROM message_embeddings
        WHERE conversation_id = $1
        """
        result = await db_manager.fetch_one(query, conversation_id)
        return result[0] if result else 0

    async def get_user_embeddings_stats(
        self,
        user_id: str
    ) -> Dict[str, Any]:
        """사용자 임베딩 통계"""
        query = """
        SELECT
            COUNT(*) as total_embeddings,
            COUNT(DISTINCT conversation_id) as conversations_count,
            MIN(created_at) as first_embedding_at,
            MAX(created_at) as last_embedding_at
        FROM message_embeddings
        WHERE user_id = $1
        """

        row = await db_manager.fetch_one(query, user_id)

        if not row:
            return {
                "total_embeddings": 0,
                "conversations_count": 0,
                "first_embedding_at": None,
                "last_embedding_at": None
            }

        return {
            "total_embeddings": row[0] or 0,
            "conversations_count": row[1] or 0,
            "first_embedding_at": row[2],
            "last_embedding_at": row[3]
        }

    async def update_conversation_summary_embedding(
        self,
        conversation_id: str,
        summary_text: str
    ) -> bool:
        """대화 요약 임베딩 업데이트"""
        try:
            # 요약 임베딩 생성
            embedding = await embedding_manager.get_embedding(summary_text, use_cache=True)

            if not embedding:
                return False

            # 메시지 수 조회
            count = await self.get_conversation_embeddings_count(conversation_id)

            # DB에 저장
            query = """
            INSERT INTO conversation_embeddings (
                conversation_id,
                summary_embedding,
                summary_text,
                message_count
            ) VALUES ($1, $2, $3, $4)
            ON CONFLICT (conversation_id)
            DO UPDATE SET
                summary_embedding = EXCLUDED.summary_embedding,
                summary_text = EXCLUDED.summary_text,
                message_count = EXCLUDED.message_count,
                updated_at = CURRENT_TIMESTAMP
            """

            await db_manager.execute(
                query,
                conversation_id,
                embedding,
                summary_text,
                count
            )

            return True

        except Exception as e:
            logger.error(f"Failed to update conversation summary embedding: {e}")
            return False


# 전역 인스턴스
message_embedding_service = MessageEmbeddingService()
