"""
스마트 캐시 매니저

쿼리 유형별 동적 TTL과 pgvector 기반 의미론적 유사 쿼리 캐싱을 지원합니다.

Features:
- 동적 TTL: 쿼리 의도, 복잡도, 응답 품질에 따른 TTL 자동 계산
- 의미 기반 캐싱: pgvector를 사용한 유사 쿼리 검색
- 캐시 통계: 히트율, 성능 지표 추적
- 자동 만료: 백그라운드 정리 작업 지원
"""

import logging
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass

from sqlalchemy import select, update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_session_ctx
from ..database.models import QueryCacheEntry, CacheStatistics
from ..config.settings import settings
from .embeddings import embedding_manager

logger = logging.getLogger(__name__)


@dataclass
class CachedResponse:
    """캐시된 응답 데이터"""
    response_data: Dict[str, Any]
    query_text: str
    query_intent: str
    similarity_score: float
    is_exact_match: bool
    cache_id: int
    ttl_remaining: int
    hit_count: int


@dataclass
class CacheResult:
    """캐시 조회 결과"""
    hit: bool
    response: Optional[CachedResponse]
    hit_type: str  # 'exact', 'semantic', 'miss'
    search_time_ms: int


class DynamicTTLCalculator:
    """
    동적 TTL 계산기

    쿼리 의도, 복잡도, 응답 품질에 따라 최적의 TTL을 계산합니다.
    """

    # 쿼리 의도별 기본 TTL (초 단위)
    BASE_TTL_BY_INTENT = {
        # 실시간 정보 - 짧은 TTL
        "realtime_info": 900,           # 15분
        "realtime_data": 1800,          # 30분
        "financial_analysis": 600,      # 10분 (주가 등 변동성 높음)

        # 분석/비교 - 중간 TTL
        "data_analysis": 86400 * 7,     # 7일
        "comparison": 86400 * 7,        # 7일
        "technical_analysis": 86400 * 14,  # 14일

        # 연구/심층 분석 - 긴 TTL
        "deep_research": 86400 * 30,    # 30일
        "complex_analysis": 86400 * 30,  # 30일

        # 생성 - 매우 긴 TTL
        "generation": 86400 * 90,       # 90일

        # 기타 - 기본값
        "information_seeking": 86400,   # 1일
        "task_execution": 3600,         # 1시간
    }

    # 쿼리 의도별 최대 TTL (초 단위)
    MAX_TTL_BY_INTENT = {
        "realtime_info": 3600,          # 1시간
        "realtime_data": 3600,          # 1시간
        "financial_analysis": 3600,     # 1시간
        "data_analysis": 86400 * 90,    # 90일
        "comparison": 86400 * 60,       # 60일
        "technical_analysis": 86400 * 90,  # 90일
        "deep_research": 86400 * 180,   # 180일
        "complex_analysis": 86400 * 180,  # 180일
        "generation": 86400 * 365,      # 365일
        "information_seeking": 86400 * 7,  # 7일
        "task_execution": 86400,        # 1일
    }

    @classmethod
    def calculate_ttl(
        cls,
        query_intent: str,
        complexity_score: float,
        quality_score: float,
        custom_config: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        동적 TTL 계산

        Args:
            query_intent: 쿼리 의도 (예: 'realtime_info', 'deep_research')
            complexity_score: 쿼리 복잡도 (0.0~1.0)
            quality_score: 응답 품질 점수 (0.0~1.0)
            custom_config: 커스텀 설정 (선택적)

        Returns:
            int: 계산된 TTL (초)
        """
        # 1. 기본 TTL 결정
        base_ttl = cls.BASE_TTL_BY_INTENT.get(query_intent, 3600)  # 기본 1시간
        max_ttl = cls.MAX_TTL_BY_INTENT.get(query_intent, 86400 * 30)  # 기본 최대 30일

        # 2. 품질 점수에 따른 승수 (0.5x ~ 2.0x)
        # 품질이 높을수록 더 오래 캐싱
        quality_multiplier = 0.5 + (quality_score * 1.5)

        # 3. 복잡도에 따른 승수 (1.0x ~ 2.5x)
        # 복잡한 쿼리는 처리 비용이 높으므로 더 오래 캐싱
        complexity_multiplier = 1.0 + (complexity_score * 1.5)

        # 4. 최종 TTL 계산
        calculated_ttl = int(base_ttl * quality_multiplier * complexity_multiplier)

        # 5. 최대 TTL 제한
        final_ttl = min(calculated_ttl, max_ttl)

        # 6. 최소 TTL 보장 (5분)
        final_ttl = max(final_ttl, 300)

        logger.debug(
            f"TTL calculated: intent={query_intent}, base={base_ttl}, "
            f"quality_mult={quality_multiplier:.2f}, complexity_mult={complexity_multiplier:.2f}, "
            f"final={final_ttl}"
        )

        return final_ttl

    @classmethod
    def get_ttl_info(cls, query_intent: str) -> Dict[str, int]:
        """특정 의도의 TTL 정보 반환"""
        return {
            "base_ttl": cls.BASE_TTL_BY_INTENT.get(query_intent, 3600),
            "max_ttl": cls.MAX_TTL_BY_INTENT.get(query_intent, 86400 * 30),
        }


class SmartCacheManager:
    """
    스마트 캐시 매니저

    pgvector를 사용한 의미론적 캐싱과 동적 TTL을 지원합니다.
    """

    def __init__(
        self,
        similarity_threshold: float = None,
        max_cache_entries: int = None,
        enable_statistics: bool = True
    ):
        """
        Args:
            similarity_threshold: 유사도 임계값 (기본값: settings에서 가져옴)
            max_cache_entries: 최대 캐시 엔트리 수 (기본값: settings에서 가져옴)
            enable_statistics: 통계 수집 활성화 여부
        """
        self.similarity_threshold = similarity_threshold or getattr(
            settings, 'SMART_CACHE_SIMILARITY_THRESHOLD', 0.85
        )
        self.max_cache_entries = max_cache_entries or getattr(
            settings, 'SMART_CACHE_MAX_ENTRIES', 100000
        )
        self.enable_statistics = enable_statistics
        self.ttl_calculator = DynamicTTLCalculator()

    async def get_cached_response(
        self,
        query: str,
        query_vector: List[float] = None,
        query_intent: str = None,
        user_id: str = None,
        max_age_seconds: int = None
    ) -> CacheResult:
        """
        캐시된 응답 조회

        1. 정확한 쿼리 해시 매칭 시도
        2. 매칭 실패 시 의미론적 유사도 검색

        Args:
            query: 검색할 쿼리
            query_vector: 쿼리 임베딩 벡터 (없으면 자동 생성)
            query_intent: 쿼리 의도 (필터링에 사용)
            user_id: 사용자 ID (멀티테넌시)
            max_age_seconds: 최대 캐시 수명 제한

        Returns:
            CacheResult: 캐시 조회 결과
        """
        start_time = datetime.utcnow()

        try:
            async with get_session_ctx() as session:
                # 1. 정확한 해시 매칭 시도
                query_hash = self._generate_query_hash(query)
                exact_result = await self._find_exact_match(
                    session, query_hash, user_id, max_age_seconds
                )

                if exact_result:
                    search_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    await self._update_hit_statistics(session, exact_result.cache_id)

                    if self.enable_statistics:
                        await self._record_cache_hit(
                            session, query_intent or "unknown", "exact"
                        )

                    logger.info(f"캐시 정확 매칭: query_hash={query_hash[:16]}...")
                    return CacheResult(
                        hit=True,
                        response=exact_result,
                        hit_type="exact",
                        search_time_ms=search_time
                    )

                # 2. 의미론적 유사도 검색
                if query_vector is None:
                    embeddings = await embedding_manager.get_embedding(query)
                    if not embeddings or len(embeddings) == 0:
                        logger.warning("쿼리 임베딩 생성 실패")
                        search_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                        return CacheResult(
                            hit=False,
                            response=None,
                            hit_type="miss",
                            search_time_ms=search_time
                        )
                    query_vector = embeddings

                semantic_result = await self._find_similar_query(
                    session, query_vector, query_intent, user_id, max_age_seconds
                )

                search_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                if semantic_result:
                    await self._update_hit_statistics(session, semantic_result.cache_id)

                    if self.enable_statistics:
                        await self._record_cache_hit(
                            session, query_intent or "unknown", "semantic"
                        )

                    logger.info(
                        f"캐시 시맨틱 매칭: similarity={semantic_result.similarity_score:.3f}"
                    )
                    return CacheResult(
                        hit=True,
                        response=semantic_result,
                        hit_type="semantic",
                        search_time_ms=search_time
                    )

                # 3. 캐시 미스
                if self.enable_statistics:
                    await self._record_cache_miss(session, query_intent or "unknown")

                logger.debug("캐시 미스")
                return CacheResult(
                    hit=False,
                    response=None,
                    hit_type="miss",
                    search_time_ms=search_time
                )

        except Exception as e:
            logger.error(f"캐시 조회 에러: {e}")
            search_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            return CacheResult(
                hit=False,
                response=None,
                hit_type="error",
                search_time_ms=search_time
            )

    async def set_cached_response(
        self,
        query: str,
        query_vector: List[float],
        query_intent: str,
        complexity_score: float,
        response_data: Dict[str, Any],
        quality_score: float,
        user_id: str = None,
        session_id: str = None,
        custom_ttl: int = None,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        응답을 캐시에 저장

        Args:
            query: 원본 쿼리
            query_vector: 쿼리 임베딩 벡터
            query_intent: 쿼리 의도
            complexity_score: 쿼리 복잡도 (0.0~1.0)
            response_data: 캐시할 응답 데이터
            quality_score: 응답 품질 점수 (0.0~1.0)
            user_id: 사용자 ID (선택적)
            session_id: 세션 ID (선택적)
            custom_ttl: 커스텀 TTL (선택적)
            metadata: 추가 메타데이터 (선택적)

        Returns:
            bool: 저장 성공 여부
        """
        try:
            # TTL 계산
            if custom_ttl:
                ttl = custom_ttl
            else:
                ttl = self.ttl_calculator.calculate_ttl(
                    query_intent=query_intent,
                    complexity_score=complexity_score,
                    quality_score=quality_score
                )

            expires_at = datetime.utcnow() + timedelta(seconds=ttl)
            query_hash = self._generate_query_hash(query)

            async with get_session_ctx() as session:
                # 기존 캐시 확인 (중복 방지)
                existing = await session.execute(
                    select(QueryCacheEntry).where(
                        QueryCacheEntry.query_hash == query_hash,
                        QueryCacheEntry.user_id == user_id if user_id else True
                    )
                )
                existing_entry = existing.scalar_one_or_none()

                if existing_entry:
                    # 기존 엔트리 업데이트
                    existing_entry.response_data = response_data
                    existing_entry.response_quality_score = quality_score
                    existing_entry.ttl_seconds = ttl
                    existing_entry.expires_at = expires_at
                    existing_entry.updated_at = datetime.utcnow()
                    if metadata:
                        existing_entry.cache_metadata = metadata
                    logger.debug(f"캐시 엔트리 업데이트: id={existing_entry.id}")
                else:
                    # 새 엔트리 생성
                    new_entry = QueryCacheEntry(
                        query_text=query,
                        query_hash=query_hash,
                        query_vector=query_vector,
                        query_intent=query_intent,
                        complexity_score=complexity_score,
                        response_data=response_data,
                        response_quality_score=quality_score,
                        ttl_seconds=ttl,
                        expires_at=expires_at,
                        user_id=user_id,
                        session_id=session_id,
                        cache_metadata=metadata or {}
                    )
                    session.add(new_entry)
                    logger.debug(f"새 캐시 엔트리 생성: hash={query_hash[:16]}...")

                await session.commit()

                # 캐시 크기 관리
                await self._manage_cache_size(session)

                logger.info(
                    f"캐시 저장 완료: intent={query_intent}, ttl={ttl}s, "
                    f"quality={quality_score:.2f}"
                )
                return True

        except Exception as e:
            logger.error(f"캐시 저장 에러: {e}")
            return False

    async def _find_exact_match(
        self,
        session: AsyncSession,
        query_hash: str,
        user_id: str = None,
        max_age_seconds: int = None
    ) -> Optional[CachedResponse]:
        """정확한 해시 매칭으로 캐시 찾기"""
        now = datetime.utcnow()

        query = select(QueryCacheEntry).where(
            QueryCacheEntry.query_hash == query_hash,
            QueryCacheEntry.expires_at > now
        )

        if user_id:
            query = query.where(
                (QueryCacheEntry.user_id == user_id) |
                (QueryCacheEntry.user_id.is_(None))  # 공용 캐시도 포함
            )

        if max_age_seconds:
            min_created = now - timedelta(seconds=max_age_seconds)
            query = query.where(QueryCacheEntry.created_at >= min_created)

        result = await session.execute(query)
        entry = result.scalar_one_or_none()

        if entry:
            ttl_remaining = int((entry.expires_at - now).total_seconds())
            return CachedResponse(
                response_data=entry.response_data,
                query_text=entry.query_text,
                query_intent=entry.query_intent,
                similarity_score=1.0,
                is_exact_match=True,
                cache_id=entry.id,
                ttl_remaining=ttl_remaining,
                hit_count=entry.hit_count
            )

        return None

    async def _find_similar_query(
        self,
        session: AsyncSession,
        query_vector: List[float],
        query_intent: str = None,
        user_id: str = None,
        max_age_seconds: int = None
    ) -> Optional[CachedResponse]:
        """pgvector를 사용한 유사 쿼리 검색

        HNSW 인덱스 성능 최적화:
        - ef_search = 40: 균형잡힌 정확도와 속도 (기본값)
        - ef_search를 높이면 정확도 향상, 속도 저하
        - ef_search를 낮추면 속도 향상, 정확도 저하
        """
        now = datetime.utcnow()

        # HNSW 인덱스 런타임 파라미터 설정
        # ef_search: 검색 시 탐색할 후보 수 (기본값: 40)
        await session.execute(text("SET LOCAL hnsw.ef_search = 40"))

        # pgvector 코사인 거리 연산자 사용
        # 1 - distance = similarity
        vector_str = f"[{','.join(map(str, query_vector))}]"

        # Raw SQL for pgvector similarity search
        # Note: NULL 파라미터의 타입 추론 문제를 피하기 위해 동적 WHERE 절 구성
        where_conditions = ["expires_at > :now"]
        params = {
            "query_vector": vector_str,
            "now": now,
            "threshold": self.similarity_threshold
        }

        if query_intent is not None:
            where_conditions.append("query_intent = :intent")
            params["intent"] = query_intent

        if user_id is not None:
            where_conditions.append("(user_id = :user_id OR user_id IS NULL)")
            params["user_id"] = user_id

        if max_age_seconds is not None:
            min_created = now - timedelta(seconds=max_age_seconds)
            where_conditions.append("created_at >= :min_created")
            params["min_created"] = min_created

        where_conditions.append("1 - (query_vector <=> CAST(:query_vector AS vector)) >= :threshold")

        where_clause = " AND ".join(where_conditions)

        sql = text(f"""
            SELECT
                id,
                query_text,
                query_intent,
                response_data,
                response_quality_score,
                complexity_score,
                expires_at,
                hit_count,
                1 - (query_vector <=> CAST(:query_vector AS vector)) as similarity
            FROM query_cache
            WHERE {where_clause}
            ORDER BY query_vector <=> CAST(:query_vector AS vector)
            LIMIT 1
        """)

        result = await session.execute(sql, params)

        row = result.fetchone()

        if row:
            ttl_remaining = int((row.expires_at - now).total_seconds())
            return CachedResponse(
                response_data=row.response_data,
                query_text=row.query_text,
                query_intent=row.query_intent,
                similarity_score=float(row.similarity),
                is_exact_match=False,
                cache_id=row.id,
                ttl_remaining=ttl_remaining,
                hit_count=row.hit_count
            )

        return None

    async def _update_hit_statistics(
        self,
        session: AsyncSession,
        cache_id: int
    ) -> None:
        """캐시 히트 통계 업데이트"""
        await session.execute(
            update(QueryCacheEntry)
            .where(QueryCacheEntry.id == cache_id)
            .values(
                hit_count=QueryCacheEntry.hit_count + 1,
                last_accessed_at=datetime.utcnow()
            )
        )
        await session.commit()

    async def _record_cache_hit(
        self,
        session: AsyncSession,
        query_intent: str,
        hit_type: str
    ) -> None:
        """캐시 히트 기록"""
        time_bucket = self._get_time_bucket()

        try:
            # 기존 통계 조회
            result = await session.execute(
                select(CacheStatistics).where(
                    CacheStatistics.time_bucket == time_bucket,
                    CacheStatistics.query_intent == query_intent
                )
            )
            stats = result.scalar_one_or_none()

            if stats:
                stats.total_requests += 1
                stats.cache_hits += 1
                if hit_type == "exact":
                    stats.exact_hits += 1
                else:
                    stats.semantic_hits += 1
            else:
                stats = CacheStatistics(
                    time_bucket=time_bucket,
                    query_intent=query_intent,
                    total_requests=1,
                    cache_hits=1,
                    exact_hits=1 if hit_type == "exact" else 0,
                    semantic_hits=1 if hit_type == "semantic" else 0
                )
                session.add(stats)

            await session.commit()
        except Exception as e:
            logger.warning(f"캐시 통계 기록 실패: {e}")

    async def _record_cache_miss(
        self,
        session: AsyncSession,
        query_intent: str
    ) -> None:
        """캐시 미스 기록"""
        time_bucket = self._get_time_bucket()

        try:
            result = await session.execute(
                select(CacheStatistics).where(
                    CacheStatistics.time_bucket == time_bucket,
                    CacheStatistics.query_intent == query_intent
                )
            )
            stats = result.scalar_one_or_none()

            if stats:
                stats.total_requests += 1
                stats.cache_misses += 1
            else:
                stats = CacheStatistics(
                    time_bucket=time_bucket,
                    query_intent=query_intent,
                    total_requests=1,
                    cache_misses=1
                )
                session.add(stats)

            await session.commit()
        except Exception as e:
            logger.warning(f"캐시 미스 통계 기록 실패: {e}")

    async def _manage_cache_size(self, session: AsyncSession) -> None:
        """캐시 크기 관리 - 최대 크기 초과 시 오래된 항목 삭제"""
        try:
            # 현재 캐시 크기 확인
            count_result = await session.execute(
                select(func.count(QueryCacheEntry.id))
            )
            current_count = count_result.scalar()

            if current_count > self.max_cache_entries:
                # 초과분 + 10% 버퍼 삭제
                delete_count = int((current_count - self.max_cache_entries) * 1.1)

                # 가장 오래되고 적게 사용된 항목 삭제
                subquery = (
                    select(QueryCacheEntry.id)
                    .order_by(
                        QueryCacheEntry.last_accessed_at.asc().nullsfirst(),
                        QueryCacheEntry.hit_count.asc()
                    )
                    .limit(delete_count)
                )

                await session.execute(
                    delete(QueryCacheEntry).where(
                        QueryCacheEntry.id.in_(subquery)
                    )
                )
                await session.commit()

                logger.info(f"캐시 정리: {delete_count}개 항목 삭제")
        except Exception as e:
            logger.warning(f"캐시 크기 관리 실패: {e}")

    async def cleanup_expired(self) -> int:
        """만료된 캐시 엔트리 정리"""
        try:
            async with get_session_ctx() as session:
                result = await session.execute(
                    delete(QueryCacheEntry).where(
                        QueryCacheEntry.expires_at <= datetime.utcnow()
                    )
                )
                await session.commit()

                deleted_count = result.rowcount
                logger.info(f"만료 캐시 정리: {deleted_count}개 삭제")
                return deleted_count
        except Exception as e:
            logger.error(f"만료 캐시 정리 에러: {e}")
            return 0

    async def get_cache_statistics(
        self,
        query_intent: str = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """캐시 통계 조회"""
        try:
            async with get_session_ctx() as session:
                min_time = datetime.utcnow() - timedelta(hours=hours)

                query = select(CacheStatistics).where(
                    CacheStatistics.time_bucket >= min_time
                )

                if query_intent:
                    query = query.where(CacheStatistics.query_intent == query_intent)

                result = await session.execute(query)
                stats_list = result.scalars().all()

                total_requests = sum(s.total_requests for s in stats_list)
                total_hits = sum(s.cache_hits for s in stats_list)
                exact_hits = sum(s.exact_hits for s in stats_list)
                semantic_hits = sum(s.semantic_hits for s in stats_list)

                hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0

                # 캐시 크기 조회
                count_result = await session.execute(
                    select(func.count(QueryCacheEntry.id))
                )
                cache_size = count_result.scalar()

                return {
                    "period_hours": hours,
                    "total_requests": total_requests,
                    "total_hits": total_hits,
                    "exact_hits": exact_hits,
                    "semantic_hits": semantic_hits,
                    "cache_misses": total_requests - total_hits,
                    "hit_rate_percent": round(hit_rate, 2),
                    "cache_entries": cache_size,
                    "max_entries": self.max_cache_entries,
                    "similarity_threshold": self.similarity_threshold
                }

        except Exception as e:
            logger.error(f"통계 조회 에러: {e}")
            return {}

    async def invalidate_by_intent(self, query_intent: str) -> int:
        """특정 의도의 캐시 무효화"""
        try:
            async with get_session_ctx() as session:
                result = await session.execute(
                    delete(QueryCacheEntry).where(
                        QueryCacheEntry.query_intent == query_intent
                    )
                )
                await session.commit()

                deleted_count = result.rowcount
                logger.info(f"의도별 캐시 무효화: intent={query_intent}, count={deleted_count}")
                return deleted_count
        except Exception as e:
            logger.error(f"캐시 무효화 에러: {e}")
            return 0


    async def invalidate_by_user(self, user_id: str) -> int:
        """특정 사용자의 캐시 무효화"""
        try:
            async with get_session_ctx() as session:
                result = await session.execute(
                    delete(QueryCacheEntry).where(
                        QueryCacheEntry.user_id == user_id
                    )
                )
                await session.commit()

                deleted_count = result.rowcount
                logger.info(f"사용자별 캐시 무효화: user_id={user_id}, count={deleted_count}")
                return deleted_count
        except Exception as e:
            logger.error(f"캐시 무효화 에러: {e}")
            return 0


    async def clear_all(self) -> int:
        """모든 캐시 삭제"""
        try:
            async with get_session_ctx() as session:
                result = await session.execute(delete(QueryCacheEntry))
                await session.commit()

                deleted_count = result.rowcount
                logger.info(f"전체 캐시 삭제: {deleted_count}개")
                return deleted_count
        except Exception as e:
            logger.error(f"전체 캐시 삭제 에러: {e}")
            return 0

    def _generate_query_hash(self, query: str) -> str:
        """쿼리 해시 생성"""
        normalized = query.strip().lower()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    def _get_time_bucket(self) -> datetime:
        """현재 시간 버킷 (1시간 단위)"""
        now = datetime.utcnow()
        return now.replace(minute=0, second=0, microsecond=0)


# 전역 인스턴스
smart_cache_manager = SmartCacheManager()
