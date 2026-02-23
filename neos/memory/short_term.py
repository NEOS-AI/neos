import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from neos.memory.base import MemoryStore, MemoryItem
from neos.utils.cache import CacheManager

logger = logging.getLogger(__name__)


class ShortTermMemory(MemoryStore):
    """Redis 기반 단기 메모리

    세션별 working memory를 관리합니다:
    - 핵심 발견사항, 중간 결과, 기각된 가설 등 저장
    - 세션 종료 시 자동 만료 (TTL 기반)
    - Key 패턴: memory:short:{user_id}:{session_id}:{key}

    기존 CacheManager를 재사용하여 Redis 연결 풀을 공유합니다.
    """

    def __init__(self, cache_manager: CacheManager, ttl: int = 3600):
        """
        Args:
            cache_manager: 기존 Redis CacheManager 인스턴스
            ttl: 메모리 만료 시간 (초, 기본 1시간)
        """
        self._cache = cache_manager
        self._ttl = ttl
        self._session_id: Optional[str] = None

    def set_session(self, session_id: str) -> None:
        """현재 세션 ID 설정"""
        self._session_id = session_id

    def _make_key(self, user_id: str, key: str) -> str:
        session = self._session_id or "default"
        return f"memory:short:{user_id}:{session}:{key}"

    def _make_index_key(self, user_id: str) -> str:
        session = self._session_id or "default"
        return f"memory:short:index:{user_id}:{session}"

    async def store(
        self,
        user_id: str,
        key: str,
        value: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        cache_key = self._make_key(user_id, key)
        item = {
            "key": key,
            "content": value,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }

        success = await self._cache.set(cache_key, item, ttl=self._ttl)
        if success:
            # 인덱스에 키 추가 (검색용)
            index_key = self._make_index_key(user_id)
            try:
                if self._cache.redis_client:
                    await self._cache.redis_client.sadd(index_key, key)
                    await self._cache.redis_client.expire(index_key, self._ttl)
            except Exception as e:
                logger.debug(f"Short-term memory index update failed: {e}")

        return success

    async def retrieve(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> List[MemoryItem]:
        """세션 내 모든 메모리 항목 반환 (단기 메모리는 semantic search 불필요)

        단기 메모리는 양이 적으므로 모든 항목을 반환하고
        상위 레이어에서 필터링합니다.
        """
        index_key = self._make_index_key(user_id)
        items = []

        try:
            if not self._cache.redis_client:
                return items

            keys = await self._cache.redis_client.smembers(index_key)
            if not keys:
                return items

            for raw_key in list(keys)[:limit]:
                key_str = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
                cache_key = self._make_key(user_id, key_str)
                data = await self._cache.get(cache_key)
                if data:
                    items.append(MemoryItem(
                        key=data["key"],
                        content=data["content"],
                        metadata=data.get("metadata", {}),
                        score=1.0,  # 단기 메모리는 모두 현재 세션이므로 최대 점수
                        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
                    ))
        except Exception as e:
            logger.warning(f"Short-term memory retrieval failed: {e}")

        return items

    async def delete(self, user_id: str, key: str) -> bool:
        cache_key = self._make_key(user_id, key)
        success = await self._cache.delete(cache_key)

        # 인덱스에서도 제거
        try:
            index_key = self._make_index_key(user_id)
            if self._cache.redis_client:
                await self._cache.redis_client.srem(index_key, key)
        except Exception:
            pass

        return success

    async def clear_session(self, user_id: str, session_id: Optional[str] = None) -> int:
        """세션의 모든 단기 메모리 삭제"""
        sid = session_id or self._session_id or "default"
        pattern = f"memory:short:{user_id}:{sid}:*"
        deleted = await self._cache.delete_pattern(pattern)

        # 인덱스도 삭제
        index_key = f"memory:short:index:{user_id}:{sid}"
        await self._cache.delete(index_key)

        logger.info(f"Cleared {deleted} short-term memories for user={user_id}, session={sid}")
        return deleted
