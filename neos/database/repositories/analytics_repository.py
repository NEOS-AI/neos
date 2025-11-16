"""Analytics Repository - 웹 검색 분석 데이터 접근 레이어

이 모듈은 Repository 패턴을 구현하여 웹 검색 분석 관련 모든 데이터베이스 쿼리를
캡슐화하고, 비즈니스 로직으로부터 데이터 접근 로직을 분리합니다.
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.database.connection import db_manager


class AnalyticsRepository:
    """웹 검색 분석 데이터 리포지토리

    모든 SQL 쿼리를 캡슐화하여 서비스 레이어에서 데이터베이스 접근 로직을 분리합니다.
    """

    # ==================== 인기 쿼리 ====================

    @staticmethod
    async def get_popular_queries(
        session: AsyncSession,
        engine_name: Optional[str],
        period_days: int,
        limit: int
    ) -> List[Any]:
        """인기 검색 쿼리 조회

        Args:
            session: 데이터베이스 세션
            engine_name: 필터링할 엔진 이름 (None이면 전체)
            period_days: 분석 기간 (일수)
            limit: 반환할 최대 결과 수

        Returns:
            인기 쿼리 결과 목록
        """
        query = text("""
            SELECT * FROM get_popular_queries(:engine_name, :period_days, :limit)
        """)

        result = await session.execute(
            query,
            {
                "engine_name": engine_name,
                "period_days": period_days,
                "limit": limit
            }
        )
        return result.fetchall()

    # ==================== 엔진 통계 ====================

    @staticmethod
    async def get_engine_statistics(
        session: AsyncSession,
        period_days: int
    ) -> List[Any]:
        """검색 엔진별 통계 조회

        Args:
            session: 데이터베이스 세션
            period_days: 분석 기간 (일수)

        Returns:
            엔진별 통계 결과 목록
        """
        query = text("""
            SELECT * FROM get_engine_statistics(:period_days)
        """)

        result = await session.execute(query, {"period_days": period_days})
        return result.fetchall()

    # ==================== 검색 트렌드 ====================

    @staticmethod
    async def get_search_trends(
        session: AsyncSession,
        engine_name: Optional[str],
        period_days: int,
        interval: str
    ) -> List[Any]:
        """검색 트렌드 조회

        Args:
            session: 데이터베이스 세션
            engine_name: 필터링할 엔진 이름
            period_days: 분석 기간 (일수)
            interval: 트렌드 간격 ('hour', 'day', 'week')

        Returns:
            트렌드 데이터 결과 목록
        """
        query = text("""
            SELECT * FROM get_search_trends(:engine_name, :period_days, :interval)
        """)

        result = await session.execute(
            query,
            {
                "engine_name": engine_name,
                "period_days": period_days,
                "interval": interval
            }
        )
        return result.fetchall()

    # ==================== 일일/주간/월간 통계 ====================

    @staticmethod
    async def get_daily_statistics(
        session: AsyncSession,
        engine_name: Optional[str],
        limit: int
    ) -> List[Any]:
        """일일 통계 조회

        Args:
            session: 데이터베이스 세션
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 일수

        Returns:
            일일 통계 결과 목록
        """
        query_text = """
            SELECT * FROM daily_search_statistics
            WHERE 1=1
        """
        params = {"limit": limit}

        if engine_name:
            query_text += " AND engine_name = :engine_name"
            params["engine_name"] = engine_name

        query_text += " ORDER BY search_date DESC LIMIT :limit"

        result = await session.execute(text(query_text), params)
        return result.fetchall()

    @staticmethod
    async def get_weekly_statistics(
        session: AsyncSession,
        engine_name: Optional[str],
        limit: int
    ) -> List[Any]:
        """주간 통계 조회

        Args:
            session: 데이터베이스 세션
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 주수

        Returns:
            주간 통계 결과 목록
        """
        query_text = """
            SELECT * FROM weekly_search_statistics
            WHERE 1=1
        """
        params = {"limit": limit}

        if engine_name:
            query_text += " AND engine_name = :engine_name"
            params["engine_name"] = engine_name

        query_text += " ORDER BY week_start DESC LIMIT :limit"

        result = await session.execute(text(query_text), params)
        return result.fetchall()

    @staticmethod
    async def get_monthly_statistics(
        session: AsyncSession,
        engine_name: Optional[str],
        limit: int
    ) -> List[Any]:
        """월간 통계 조회

        Args:
            session: 데이터베이스 세션
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 월수

        Returns:
            월간 통계 결과 목록
        """
        query_text = """
            SELECT * FROM monthly_search_statistics
            WHERE 1=1
        """
        params = {"limit": limit}

        if engine_name:
            query_text += " AND engine_name = :engine_name"
            params["engine_name"] = engine_name

        query_text += " ORDER BY month_start DESC LIMIT :limit"

        result = await session.execute(text(query_text), params)
        return result.fetchall()

    # ==================== 품질 분석 ====================

    @staticmethod
    async def get_quality_analysis(
        session: AsyncSession,
        engine_name: Optional[str],
        limit: int
    ) -> List[Any]:
        """검색 품질 분석 조회

        Args:
            session: 데이터베이스 세션
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 일수

        Returns:
            품질 분석 결과 목록
        """
        query_text = """
            SELECT * FROM search_quality_analysis
            WHERE 1=1
        """
        params = {"limit": limit}

        if engine_name:
            query_text += " AND engine_name = :engine_name"
            params["engine_name"] = engine_name

        query_text += " ORDER BY search_date DESC LIMIT :limit"

        result = await session.execute(text(query_text), params)
        return result.fetchall()

    # ==================== 사용자 검색 패턴 ====================

    @staticmethod
    async def get_user_search_patterns(
        session: AsyncSession,
        user_id: str,
        period_days: int
    ) -> List[Any]:
        """사용자 검색 패턴 조회

        Args:
            session: 데이터베이스 세션
            user_id: 사용자 ID
            period_days: 분석 기간 (일수)

        Returns:
            사용자 검색 패턴 결과 목록
        """
        query = text("""
            SELECT * FROM get_user_search_patterns(:user_id, :period_days)
        """)

        result = await session.execute(
            query,
            {
                "user_id": user_id,
                "period_days": period_days
            }
        )
        return result.fetchall()

    # ==================== 분석 요약 ====================

    @staticmethod
    async def get_total_statistics(
        session: AsyncSession,
        period_days: int
    ) -> Any:
        """전체 통계 조회

        Args:
            session: 데이터베이스 세션
            period_days: 분석 기간 (일수)

        Returns:
            전체 통계 결과
        """
        query = text("""
            SELECT
                COUNT(*) as total_queries,
                COUNT(DISTINCT engine_name) as total_engines,
                COUNT(DISTINCT user_id) as total_users,
                ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
                ROUND(
                    (COUNT(CASE WHEN status = 'completed' THEN 1 END)::numeric / COUNT(*)::numeric),
                    3
                ) as success_rate
            FROM web_search_queries
            WHERE executed_at > NOW() - :period::interval
        """)

        result = await session.execute(query, {"period": f"{period_days} days"})
        return result.fetchone()

    @staticmethod
    async def get_top_engine(
        session: AsyncSession,
        period_days: int
    ) -> Optional[Any]:
        """가장 많이 사용된 엔진 조회

        Args:
            session: 데이터베이스 세션
            period_days: 분석 기간 (일수)

        Returns:
            가장 많이 사용된 엔진 결과
        """
        query = text("""
            SELECT engine_name, COUNT(*) as cnt
            FROM web_search_queries
            WHERE executed_at > NOW() - :period::interval
            GROUP BY engine_name
            ORDER BY cnt DESC
            LIMIT 1
        """)

        result = await session.execute(query, {"period": f"{period_days} days"})
        return result.fetchone()

    @staticmethod
    async def get_top_query(
        session: AsyncSession,
        period_days: int
    ) -> Optional[Any]:
        """가장 많이 검색된 쿼리 조회

        Args:
            session: 데이터베이스 세션
            period_days: 분석 기간 (일수)

        Returns:
            가장 많이 검색된 쿼리 결과
        """
        query = text("""
            SELECT query_text, COUNT(*) as cnt
            FROM web_search_queries
            WHERE executed_at > NOW() - :period::interval
            GROUP BY query_text
            ORDER BY cnt DESC
            LIMIT 1
        """)

        result = await session.execute(query, {"period": f"{period_days} days"})
        return result.fetchone()
