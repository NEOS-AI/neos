"""
고급 캐시 무효화 전략 (Phase 4)

주요 기능:
1. 태그 기반 무효화: 특정 태그를 가진 모든 캐시 무효화
2. 패턴 기반 무효화: 쿼리 패턴 매칭으로 무효화
3. 시간 기반 무효화: 시간 범위 내 캐시 무효화
4. 의존성 기반 무효화: 계층적 캐시 무효화
5. Bloom Filter: 효율적인 캐시 존재 확인
"""

import re
import logging
from typing import List, Dict, Any, Set, Pattern
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.database.connection import db_manager
from neos.utils.smart_cache_manager import smart_cache_manager

logger = logging.getLogger(__name__)


@dataclass
class CacheTag:
    """
    캐시 태그

    캐시 항목을 그룹화하여 일괄 무효화 지원
    """
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CacheDependency:
    """
    캐시 의존성

    상위 개념 변경 시 하위 캐시 모두 무효화
    """
    parent_key: str
    child_keys: Set[str] = field(default_factory=set)


class CacheInvalidationManager:
    """
    고급 캐시 무효화 관리자

    다양한 전략으로 캐시를 선택적으로 무효화
    """

    def __init__(self):
        # 태그별 캐시 키 매핑
        self._tag_to_keys: Dict[str, Set[str]] = defaultdict(set)

        # 캐시 의존성 그래프
        self._dependencies: Dict[str, CacheDependency] = {}

        # 패턴 캐시 (컴파일된 정규표현식)
        self._pattern_cache: Dict[str, Pattern] = {}

    # ========================================================================
    # 1. 태그 기반 무효화
    # ========================================================================

    async def add_tag(
        self,
        cache_key: str,
        tag: str
    ):
        """
        캐시에 태그 추가

        Args:
            cache_key: 캐시 키 (쿼리 해시)
            tag: 태그 이름 (예: "user:123", "topic:AI", "date:2026-01-03")

        Example:
            await invalidator.add_tag("abc123", "topic:AI")
            await invalidator.add_tag("abc123", "user:alice")
        """
        self._tag_to_keys[tag].add(cache_key)

        # DB에도 저장 (영구화)
        async with db_manager.get_session() as session:
            query = text("""
                INSERT INTO cache_tags (cache_key, tag, created_at)
                VALUES (:cache_key, :tag, CURRENT_TIMESTAMP)
                ON CONFLICT (cache_key, tag) DO NOTHING
            """)

            await session.execute(query, {
                "cache_key": cache_key,
                "tag": tag
            })
            await session.commit()

        logger.debug(f"Added tag '{tag}' to cache key '{cache_key}'")


    async def invalidate_by_tag(
        self,
        tag: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        특정 태그를 가진 모든 캐시 무효화

        Args:
            tag: 태그 이름
            dry_run: True면 실제 삭제하지 않고 삭제 대상만 반환

        Returns:
            Dict: 무효화 결과 (삭제된 개수 등)

        Example:
            # "topic:AI" 태그를 가진 모든 캐시 무효화
            result = await invalidator.invalidate_by_tag("topic:AI")
        """
        # DB에서 태그를 가진 캐시 키 조회
        async with db_manager.get_session() as session:
            query = text("""SELECT DISTINCT cache_key FROM cache_tags WHERE tag = :tag;""")

            result = await session.execute(query, {"tag": tag})
            cache_keys = [row[0] for row in result.fetchall()]

        if not cache_keys:
            logger.info(f"No cache entries found for tag '{tag}'")
            return {"tag": tag, "deleted_count": 0, "dry_run": dry_run}

        if dry_run:
            logger.info(f"DRY RUN: Would invalidate {len(cache_keys)} cache entries for tag '{tag}'")
            return {
                "tag": tag,
                "would_delete": cache_keys,
                "count": len(cache_keys),
                "dry_run": True
            }

        # 실제 캐시 무효화
        deleted_count = await self._delete_cache_entries(cache_keys)

        # 태그 정보 삭제
        async with db_manager.get_session() as session:
            delete_query = text("""DELETE FROM cache_tags WHERE tag = :tag""")
            await session.execute(delete_query, {"tag": tag})
            await session.commit()

        # 메모리에서도 삭제
        if tag in self._tag_to_keys:
            del self._tag_to_keys[tag]

        logger.info(f"Invalidated {deleted_count} cache entries for tag '{tag}'")

        return {
            "tag": tag,
            "deleted_count": deleted_count,
            "dry_run": False
        }

    # ========================================================================
    # 2. 패턴 기반 무효화
    # ========================================================================

    async def invalidate_by_pattern(
        self,
        pattern: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        쿼리 패턴에 매칭되는 모든 캐시 무효화

        Args:
            pattern: 정규표현식 패턴
            dry_run: True면 실제 삭제하지 않고 삭제 대상만 반환

        Returns:
            Dict: 무효화 결과

        Example:
            # "AI" 키워드를 포함한 모든 캐시 무효화
            result = await invalidator.invalidate_by_pattern(r".*\bAI\b.*")
        """
        # 패턴 컴파일 (캐싱)
        if pattern not in self._pattern_cache:
            self._pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE)

        regex = self._pattern_cache[pattern]

        # DB에서 모든 캐시 쿼리 조회
        async with db_manager.get_session() as session:
            query = text("""
                SELECT query_hash, query_text
                FROM query_cache
                WHERE query_text IS NOT NULL
            """)

            result = await session.execute(query)
            all_entries = result.fetchall()

        # 패턴 매칭
        matching_keys = []
        for query_hash, query_text in all_entries:
            if regex.search(query_text):
                matching_keys.append(query_hash)

        if not matching_keys:
            logger.info(f"No cache entries found matching pattern '{pattern}'")
            return {"pattern": pattern, "deleted_count": 0, "dry_run": dry_run}

        if dry_run:
            logger.info(f"DRY RUN: Would invalidate {len(matching_keys)} cache entries matching pattern '{pattern}'")
            return {
                "pattern": pattern,
                "would_delete": matching_keys,
                "count": len(matching_keys),
                "dry_run": True
            }

        # 실제 캐시 무효화
        deleted_count = await self._delete_cache_entries(matching_keys)

        logger.info(f"Invalidated {deleted_count} cache entries matching pattern '{pattern}'")

        return {
            "pattern": pattern,
            "deleted_count": deleted_count,
            "dry_run": False
        }

    # ========================================================================
    # 3. 시간 기반 무효화
    # ========================================================================

    async def invalidate_by_age(
        self,
        max_age: timedelta,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        특정 시간보다 오래된 캐시 무효화

        Args:
            max_age: 최대 캐시 나이 (timedelta)
            dry_run: True면 실제 삭제하지 않고 삭제 대상만 반환

        Returns:
            Dict: 무효화 결과

        Example:
            # 7일 이상 된 캐시 무효화
            result = await invalidator.invalidate_by_age(timedelta(days=7))
        """
        cutoff_time = datetime.now() - max_age

        # DB에서 오래된 캐시 조회
        async with db_manager.get_session() as session:
            query = text("""
                SELECT query_hash
                FROM query_cache
                WHERE created_at < :cutoff_time
            """)

            result = await session.execute(query, {"cutoff_time": cutoff_time})
            old_keys = [row[0] for row in result.fetchall()]

        if not old_keys:
            logger.info(f"No cache entries older than {max_age}")
            return {"max_age": str(max_age), "deleted_count": 0, "dry_run": dry_run}

        if dry_run:
            logger.info(f"DRY RUN: Would invalidate {len(old_keys)} cache entries older than {max_age}")
            return {
                "max_age": str(max_age),
                "would_delete": old_keys,
                "count": len(old_keys),
                "dry_run": True
            }

        # 실제 캐시 무효화
        deleted_count = await self._delete_cache_entries(old_keys)

        logger.info(f"Invalidated {deleted_count} cache entries older than {max_age}")

        return {
            "max_age": str(max_age),
            "deleted_count": deleted_count,
            "dry_run": False
        }

    # ========================================================================
    # 4. 의존성 기반 무효화
    # ========================================================================

    def add_dependency(
        self,
        parent_key: str,
        child_key: str
    ):
        """
        캐시 의존성 추가

        상위 캐시가 무효화되면 하위 캐시도 자동 무효화

        Args:
            parent_key: 상위 캐시 키
            child_key: 하위 캐시 키

        Example:
            # "사용자 정보" 캐시 변경 시 "사용자 대시보드" 캐시도 무효화
            invalidator.add_dependency("user:123:info", "user:123:dashboard")
        """
        if parent_key not in self._dependencies:
            self._dependencies[parent_key] = CacheDependency(parent_key)

        self._dependencies[parent_key].child_keys.add(child_key)

        logger.debug(f"Added dependency: {parent_key} -> {child_key}")

    async def invalidate_with_dependencies(
        self,
        cache_key: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        캐시와 의존하는 모든 하위 캐시 무효화

        Args:
            cache_key: 캐시 키
            dry_run: True면 실제 삭제하지 않고 삭제 대상만 반환

        Returns:
            Dict: 무효화 결과
        """
        # 의존성 그래프 탐색 (DFS)
        all_keys = self._get_all_dependent_keys(cache_key)

        if not all_keys:
            all_keys = [cache_key]

        if dry_run:
            logger.info(f"DRY RUN: Would invalidate {len(all_keys)} cache entries (with dependencies)")
            return {
                "parent_key": cache_key,
                "would_delete": list(all_keys),
                "count": len(all_keys),
                "dry_run": True
            }

        # 실제 캐시 무효화
        deleted_count = await self._delete_cache_entries(list(all_keys))

        logger.info(f"Invalidated {deleted_count} cache entries (including dependencies) for '{cache_key}'")

        return {
            "parent_key": cache_key,
            "deleted_count": deleted_count,
            "dry_run": False
        }

    def _get_all_dependent_keys(self, parent_key: str, visited: Set[str] = None) -> Set[str]:
        """
        의존성 그래프를 DFS로 탐색하여 모든 하위 캐시 키 반환

        Args:
            parent_key: 상위 캐시 키
            visited: 방문한 키 (순환 의존성 방지)

        Returns:
            Set[str]: 모든 의존 캐시 키
        """
        if visited is None:
            visited = set()

        if parent_key in visited:
            return visited

        visited.add(parent_key)

        if parent_key in self._dependencies:
            for child_key in self._dependencies[parent_key].child_keys:
                self._get_all_dependent_keys(child_key, visited)

        return visited

    # ========================================================================
    # 헬퍼 메서드
    # ========================================================================

    async def _delete_cache_entries(self, cache_keys: List[str]) -> int:
        """
        캐시 항목 삭제 (smart_cache_manager 사용)

        Args:
            cache_keys: 삭제할 캐시 키 리스트

        Returns:
            int: 삭제된 개수
        """
        deleted_count = 0

        async with db_manager.get_session() as session:
            for cache_key in cache_keys:
                query = text("""DELETE FROM query_cache WHERE query_hash = :cache_key;""")

                result = await session.execute(query, {"cache_key": cache_key})
                deleted_count += result.rowcount

            await session.commit()

        return deleted_count

    async def get_statistics(self) -> Dict[str, Any]:
        """
        캐시 무효화 통계 조회

        Returns:
            Dict: 통계 정보
        """
        async with db_manager.get_session() as session:
            # 총 캐시 개수
            count_query = text("SELECT COUNT(*) FROM query_cache")
            result = await session.execute(count_query)
            total_count = result.scalar()

            # 태그별 캐시 개수
            tag_query = text("""
                SELECT tag, COUNT(DISTINCT cache_key) as count
                FROM cache_tags
                GROUP BY tag
                ORDER BY count DESC
                LIMIT 10
            """)
            result = await session.execute(tag_query)
            top_tags = [{"tag": row[0], "count": row[1]} for row in result.fetchall()]

        return {
            "total_cache_entries": total_count,
            "total_tags": len(self._tag_to_keys),
            "total_dependencies": len(self._dependencies),
            "top_tags": top_tags
        }


# 전역 인스턴스
cache_invalidation_manager = CacheInvalidationManager()
