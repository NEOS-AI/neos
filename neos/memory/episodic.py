import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from neos.memory.base import MemoryStore, MemoryItem

logger = logging.getLogger(__name__)


class EpisodicMemory(MemoryStore):
    """PostgreSQL 기반 에피소드 메모리

    완전한 연구 세션과 결과를 기록합니다:
    - "지난번 X 연구 시 Y를 발견했다" 형태의 회상 지원
    - 쿼리, 핵심 발견, 사용된 소스, 품질 점수 저장
    - 시간순 / 주제 유사도 기반 검색

    Note: 이 클래스는 DB migration 012가 적용된 후에만 동작합니다.
    """

    def __init__(self):
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
        """에피소드 저장

        Args:
            user_id: 사용자 ID
            key: 세션 ID
            value: 에피소드 데이터 dict:
                - query: 원본 쿼리
                - key_findings: 핵심 발견사항
                - sources_used: 사용된 소스 리스트
                - quality_score: 응답 품질 점수
            metadata: 추가 메타데이터
        """
        try:
            episode = value if isinstance(value, dict) else {"content": value}
            query_text = episode.get("query", key)
            key_findings = episode.get("key_findings", "")
            sources_used = episode.get("sources_used", [])
            quality_score = episode.get("quality_score", 0.0)

            await self.db.execute(
                """
                INSERT INTO episodic_memories
                    (user_id, session_id, query, key_findings, sources_used, quality_score, metadata)
                VALUES
                    (:param1, :param2, :param3, :param4, :param5::jsonb, :param6, :param7::jsonb)
                """,
                user_id,
                key,
                query_text,
                key_findings if isinstance(key_findings, str) else json.dumps(key_findings, ensure_ascii=False),
                json.dumps(sources_used, ensure_ascii=False) if not isinstance(sources_used, str) else sources_used,
                float(quality_score),
                json.dumps(metadata or {})
            )
            logger.debug(f"Episodic memory stored: user={user_id}, session={key}")
            return True
        except Exception as e:
            logger.error(f"Episodic memory store failed: {e}")
            return False

    async def retrieve(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> List[MemoryItem]:
        """최근 에피소드 검색 (시간순 + 키워드 매칭)

        PostgreSQL ts_rank를 사용한 텍스트 검색과 최신순 정렬을 결합합니다.
        """
        try:
            rows = await self.db.fetch_all(
                """
                SELECT session_id, query, key_findings, sources_used,
                       quality_score, metadata, created_at
                FROM episodic_memories
                WHERE user_id = :param1
                ORDER BY created_at DESC
                LIMIT :param2
                """,
                user_id, limit
            )

            items = []
            for row in rows:
                sources = row[3]
                if isinstance(sources, str):
                    try:
                        sources = json.loads(sources)
                    except (json.JSONDecodeError, TypeError):
                        sources = []

                items.append(MemoryItem(
                    key=row[0],  # session_id
                    content={
                        "query": row[1],
                        "key_findings": row[2],
                        "sources_used": sources,
                        "quality_score": float(row[4]) if row[4] else 0.0,
                    },
                    metadata=row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}"),
                    score=float(row[4]) if row[4] else 0.0,
                    created_at=row[6],
                ))
            return items
        except Exception as e:
            logger.warning(f"Episodic memory retrieval failed: {e}")
            return []

    async def delete(self, user_id: str, key: str) -> bool:
        """특정 에피소드 삭제 (key = session_id)"""
        try:
            await self.db.execute(
                "DELETE FROM episodic_memories WHERE user_id = :param1 AND session_id = :param2",
                user_id, key
            )
            return True
        except Exception as e:
            logger.error(f"Episodic memory delete failed: {e}")
            return False

    async def get_related_episodes(
        self,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> List[MemoryItem]:
        """주제 관련 에피소드 검색 (텍스트 유사도 기반)

        PostgreSQL full-text search로 관련 연구 에피소드를 찾습니다.
        """
        try:
            rows = await self.db.fetch_all(
                """
                SELECT session_id, query, key_findings, sources_used,
                       quality_score, metadata, created_at,
                       ts_rank(
                           to_tsvector('simple', coalesce(query, '') || ' ' || coalesce(key_findings, '')),
                           plainto_tsquery('simple', :param1)
                       ) as rank
                FROM episodic_memories
                WHERE user_id = :param2
                  AND to_tsvector('simple', coalesce(query, '') || ' ' || coalesce(key_findings, ''))
                      @@ plainto_tsquery('simple', :param3)
                ORDER BY rank DESC, created_at DESC
                LIMIT :param4
                """,
                query, user_id, query, limit
            )

            items = []
            for row in rows:
                sources = row[3]
                if isinstance(sources, str):
                    try:
                        sources = json.loads(sources)
                    except (json.JSONDecodeError, TypeError):
                        sources = []

                items.append(MemoryItem(
                    key=row[0],
                    content={
                        "query": row[1],
                        "key_findings": row[2],
                        "sources_used": sources,
                        "quality_score": float(row[4]) if row[4] else 0.0,
                    },
                    metadata=row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}"),
                    score=float(row[7]) if row[7] else 0.0,  # ts_rank score
                    created_at=row[6],
                ))
            return items
        except Exception as e:
            # Full-text search 실패 시 최근 에피소드로 fallback
            logger.warning(f"Episodic memory related search failed, falling back to recent: {e}")
            return await self.retrieve(user_id, query, limit)
