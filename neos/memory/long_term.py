import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from neos.memory.base import MemoryStore, MemoryItem

logger = logging.getLogger(__name__)


class LongTermMemory(MemoryStore):
    """PostgreSQL + pgvector 기반 장기 메모리

    사용자별 영구 지식을 저장하고 semantic retrieval합니다:
    - 학습된 사실, 선호 소스, 쿼리 패턴
    - embedding 기반 유사도 검색 (pgvector cosine similarity)
    - long_term_memories 테이블 사용

    Note: 이 클래스는 DB migration 012가 적용된 후에만 동작합니다.
    """

    def __init__(self):
        # Lazy import to avoid circular dependencies
        self._db = None
        self._embedding_manager = None

    @property
    def db(self):
        if self._db is None:
            from neos.database.connection import db_manager
            self._db = db_manager
        return self._db

    @property
    def embedding_manager(self):
        if self._embedding_manager is None:
            from neos.utils.embeddings import embedding_manager
            self._embedding_manager = embedding_manager
        return self._embedding_manager

    async def store(
        self,
        user_id: str,
        key: str,
        value: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

            # embedding 생성
            embedding = await self.embedding_manager.get_embedding(content)
            embedding_str = f"[{','.join(str(x) for x in embedding)}]" if embedding else None

            await self.db.execute(
                """
                INSERT INTO long_term_memories (user_id, key, content, embedding, metadata)
                VALUES (:param1, :param2, :param3, :param4::vector, :param5::jsonb)
                ON CONFLICT (user_id, key) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                user_id, key, content, embedding_str, json.dumps(metadata or {})
            )
            logger.debug(f"Long-term memory stored: user={user_id}, key={key}")
            return True
        except Exception as e:
            logger.error(f"Long-term memory store failed: {e}")
            return False

    async def retrieve(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> List[MemoryItem]:
        try:
            query_embedding = await self.embedding_manager.get_embedding(query)
            if not query_embedding:
                return []

            embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

            rows = await self.db.fetch_all(
                """
                SELECT key, content, metadata,
                       1 - (embedding::halfvec(3072) <=> :param1::halfvec(3072)) as similarity,
                       created_at
                FROM long_term_memories
                WHERE user_id = :param2
                  AND embedding IS NOT NULL
                ORDER BY embedding::halfvec(3072) <=> :param3::halfvec(3072)
                LIMIT :param4
                """,
                embedding_str, user_id, embedding_str, limit
            )

            items = []
            for row in rows:
                items.append(MemoryItem(
                    key=row[0],
                    content=row[1],
                    metadata=row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                    score=float(row[3]) if row[3] is not None else 0.0,
                    created_at=row[4] if isinstance(row[4], datetime) else None,
                ))
            return items
        except Exception as e:
            logger.warning(f"Long-term memory retrieval failed: {e}")
            return []

    async def delete(self, user_id: str, key: str) -> bool:
        try:
            await self.db.execute(
                "DELETE FROM long_term_memories WHERE user_id = :param1 AND key = :param2",
                user_id, key
            )
            return True
        except Exception as e:
            logger.error(f"Long-term memory delete failed: {e}")
            return False

    async def get_all_for_user(self, user_id: str, limit: int = 50) -> List[MemoryItem]:
        """사용자의 전체 장기 메모리 조회 (최근순)"""
        try:
            rows = await self.db.fetch_all(
                """
                SELECT key, content, metadata, created_at
                FROM long_term_memories
                WHERE user_id = :param1
                ORDER BY updated_at DESC
                LIMIT :param2
                """,
                user_id, limit
            )
            return [
                MemoryItem(
                    key=row[0],
                    content=row[1],
                    metadata=row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                    score=1.0,
                    created_at=row[3],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Long-term memory get_all failed: {e}")
            return []
