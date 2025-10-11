"""웹 검색 로그 분석 서비스

검색 로그 데이터 분석 및 통계 제공
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.database.connection import db_manager
from neos.database.web_search_analytics_types import (
    PopularQuery,
    EngineStatistics,
    SearchTrend,
    DailyStatistics,
    WeeklyStatistics,
    MonthlyStatistics,
    SearchQualityAnalysis,
    UserActivity,
    UserSearchPattern,
    SimilarQuery,
    AnalyticsPeriod,
    TrendInterval,
    PopularQueriesResponse,
    EngineStatisticsResponse,
    SearchTrendsResponse,
    AnalyticsSummary,
    ComprehensiveAnalytics
)

logger = logging.getLogger(__name__)


class WebSearchAnalyticsService:
    """웹 검색 분석 서비스"""

    @staticmethod
    def _period_to_days(period: AnalyticsPeriod) -> int:
        """분석 기간을 일수로 변환"""
        mapping = {
            AnalyticsPeriod.ONE_DAY: 1,
            AnalyticsPeriod.ONE_WEEK: 7,
            AnalyticsPeriod.ONE_MONTH: 30,
            AnalyticsPeriod.THREE_MONTHS: 90,
            AnalyticsPeriod.ONE_YEAR: 365
        }
        return mapping.get(period, 7)

    async def get_popular_queries(
        self,
        period: AnalyticsPeriod = AnalyticsPeriod.ONE_WEEK,
        engine_name: Optional[str] = None,
        limit: int = 50
    ) -> PopularQueriesResponse:
        """인기 검색 쿼리 조회

        Args:
            period: 분석 기간
            engine_name: 필터링할 엔진 이름 (None이면 전체)
            limit: 반환할 최대 결과 수

        Returns:
            PopularQueriesResponse: 인기 쿼리 목록
        """
        try:
            period_days = self._period_to_days(period)

            async with await db_manager.get_session() as session:
                result = await session.execute(
                    text("""
                        SELECT * FROM get_popular_queries(:engine_name, :period_days, :limit)
                    """),
                    {
                        "engine_name": engine_name,
                        "period_days": period_days,
                        "limit": limit
                    }
                )

                rows = result.fetchall()
                queries = [
                    PopularQuery(
                        query_text=row.query_text,
                        search_count=row.search_count,
                        unique_users=row.unique_users,
                        avg_quality_score=row.avg_quality_score,
                        avg_execution_time_ms=row.avg_execution_time_ms,
                        success_rate=row.success_rate,
                        first_searched=row.first_searched,
                        last_searched=row.last_searched,
                        engine_name=row.engine_name
                    )
                    for row in rows
                ]

                return PopularQueriesResponse(
                    period=period.value,
                    engine_name=engine_name,
                    total_count=len(queries),
                    queries=queries
                )

        except Exception as e:
            logger.error(f"Failed to get popular queries: {e}")
            raise

    async def get_engine_statistics(
        self,
        period: AnalyticsPeriod = AnalyticsPeriod.ONE_WEEK
    ) -> EngineStatisticsResponse:
        """검색 엔진별 통계 조회

        Args:
            period: 분석 기간

        Returns:
            EngineStatisticsResponse: 엔진별 통계
        """
        try:
            period_days = self._period_to_days(period)

            async with await db_manager.get_session() as session:
                result = await session.execute(
                    text("""
                        SELECT * FROM get_engine_statistics(:period_days)
                    """),
                    {"period_days": period_days}
                )

                rows = result.fetchall()
                statistics = [
                    EngineStatistics(
                        engine_name=row.engine_name,
                        total_queries=row.total_queries,
                        unique_queries=row.unique_queries,
                        unique_users=row.unique_users,
                        avg_execution_time_ms=row.avg_execution_time_ms,
                        avg_quality_score=row.avg_quality_score,
                        avg_results_count=row.avg_results_count,
                        success_rate=row.success_rate,
                        failed_queries=row.failed_queries,
                        timeout_queries=row.timeout_queries
                    )
                    for row in rows
                ]

                return EngineStatisticsResponse(
                    period=period.value,
                    total_engines=len(statistics),
                    statistics=statistics
                )

        except Exception as e:
            logger.error(f"Failed to get engine statistics: {e}")
            raise

    async def get_search_trends(
        self,
        period: AnalyticsPeriod = AnalyticsPeriod.ONE_WEEK,
        interval: TrendInterval = TrendInterval.DAY,
        engine_name: Optional[str] = None
    ) -> SearchTrendsResponse:
        """검색 트렌드 조회

        Args:
            period: 분석 기간
            interval: 트렌드 간격
            engine_name: 필터링할 엔진 이름

        Returns:
            SearchTrendsResponse: 트렌드 데이터
        """
        try:
            period_days = self._period_to_days(period)

            async with await db_manager.get_session() as session:
                result = await session.execute(
                    text("""
                        SELECT * FROM get_search_trends(:engine_name, :period_days, :interval)
                    """),
                    {
                        "engine_name": engine_name,
                        "period_days": period_days,
                        "interval": interval.value
                    }
                )

                rows = result.fetchall()
                trends = [
                    SearchTrend(
                        time_bucket=row.time_bucket,
                        search_count=row.search_count,
                        unique_queries=row.unique_queries,
                        avg_quality_score=row.avg_quality_score,
                        engine_name=row.engine_name
                    )
                    for row in rows
                ]

                return SearchTrendsResponse(
                    period=period.value,
                    interval=interval.value,
                    engine_name=engine_name,
                    trends=trends
                )

        except Exception as e:
            logger.error(f"Failed to get search trends: {e}")
            raise

    async def get_daily_statistics(
        self,
        engine_name: Optional[str] = None,
        limit: int = 30
    ) -> List[DailyStatistics]:
        """일일 통계 조회

        Args:
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 일수

        Returns:
            List[DailyStatistics]: 일일 통계 목록
        """
        try:
            async with await db_manager.get_session() as session:
                query = """
                    SELECT * FROM daily_search_statistics
                    WHERE 1=1
                """
                params = {"limit": limit}

                if engine_name:
                    query += " AND engine_name = :engine_name"
                    params["engine_name"] = engine_name

                query += " ORDER BY search_date DESC LIMIT :limit"

                result = await session.execute(text(query), params)
                rows = result.fetchall()

                return [
                    DailyStatistics(
                        search_date=row.search_date,
                        engine_name=row.engine_name,
                        total_queries=row.total_queries,
                        unique_queries=row.unique_queries,
                        unique_users=row.unique_users,
                        avg_execution_time_ms=row.avg_execution_time_ms,
                        avg_quality_score=row.avg_quality_score,
                        successful_queries=row.successful_queries,
                        failed_queries=row.failed_queries,
                        timeout_queries=row.timeout_queries
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get daily statistics: {e}")
            raise

    async def get_weekly_statistics(
        self,
        engine_name: Optional[str] = None,
        limit: int = 12
    ) -> List[WeeklyStatistics]:
        """주간 통계 조회

        Args:
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 주수

        Returns:
            List[WeeklyStatistics]: 주간 통계 목록
        """
        try:
            async with await db_manager.get_session() as session:
                query = """
                    SELECT * FROM weekly_search_statistics
                    WHERE 1=1
                """
                params = {"limit": limit}

                if engine_name:
                    query += " AND engine_name = :engine_name"
                    params["engine_name"] = engine_name

                query += " ORDER BY week_start DESC LIMIT :limit"

                result = await session.execute(text(query), params)
                rows = result.fetchall()

                return [
                    WeeklyStatistics(
                        week_start=row.week_start,
                        engine_name=row.engine_name,
                        total_queries=row.total_queries,
                        unique_queries=row.unique_queries,
                        unique_users=row.unique_users,
                        avg_execution_time_ms=row.avg_execution_time_ms,
                        avg_quality_score=row.avg_quality_score,
                        successful_queries=row.successful_queries,
                        failed_queries=row.failed_queries
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get weekly statistics: {e}")
            raise

    async def get_monthly_statistics(
        self,
        engine_name: Optional[str] = None,
        limit: int = 12
    ) -> List[MonthlyStatistics]:
        """월간 통계 조회

        Args:
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 월수

        Returns:
            List[MonthlyStatistics]: 월간 통계 목록
        """
        try:
            async with await db_manager.get_session() as session:
                query = """
                    SELECT * FROM monthly_search_statistics
                    WHERE 1=1
                """
                params = {"limit": limit}

                if engine_name:
                    query += " AND engine_name = :engine_name"
                    params["engine_name"] = engine_name

                query += " ORDER BY month_start DESC LIMIT :limit"

                result = await session.execute(text(query), params)
                rows = result.fetchall()

                return [
                    MonthlyStatistics(
                        month_start=row.month_start,
                        engine_name=row.engine_name,
                        total_queries=row.total_queries,
                        unique_queries=row.unique_queries,
                        unique_users=row.unique_users,
                        avg_execution_time_ms=row.avg_execution_time_ms,
                        avg_quality_score=row.avg_quality_score,
                        successful_queries=row.successful_queries,
                        failed_queries=row.failed_queries
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get monthly statistics: {e}")
            raise

    async def get_quality_analysis(
        self,
        engine_name: Optional[str] = None,
        limit: int = 30
    ) -> List[SearchQualityAnalysis]:
        """검색 품질 분석 조회

        Args:
            engine_name: 필터링할 엔진 이름
            limit: 반환할 최대 일수

        Returns:
            List[SearchQualityAnalysis]: 품질 분석 목록
        """
        try:
            async with await db_manager.get_session() as session:
                query = """
                    SELECT * FROM search_quality_analysis
                    WHERE 1=1
                """
                params = {"limit": limit}

                if engine_name:
                    query += " AND engine_name = :engine_name"
                    params["engine_name"] = engine_name

                query += " ORDER BY search_date DESC LIMIT :limit"

                result = await session.execute(text(query), params)
                rows = result.fetchall()

                return [
                    SearchQualityAnalysis(
                        engine_name=row.engine_name,
                        search_date=row.search_date,
                        total_queries=row.total_queries,
                        avg_quality_score=row.avg_quality_score,
                        avg_results_count=row.avg_results_count,
                        avg_execution_time_ms=row.avg_execution_time_ms,
                        high_quality_queries=row.high_quality_queries,
                        low_quality_queries=row.low_quality_queries
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get quality analysis: {e}")
            raise

    async def get_user_search_patterns(
        self,
        user_id: str,
        period: AnalyticsPeriod = AnalyticsPeriod.ONE_MONTH
    ) -> List[UserSearchPattern]:
        """사용자 검색 패턴 조회

        Args:
            user_id: 사용자 ID
            period: 분석 기간

        Returns:
            List[UserSearchPattern]: 사용자 검색 패턴
        """
        try:
            period_days = self._period_to_days(period)

            async with await db_manager.get_session() as session:
                result = await session.execute(
                    text("""
                        SELECT * FROM get_user_search_patterns(:user_id, :period_days)
                    """),
                    {
                        "user_id": user_id,
                        "period_days": period_days
                    }
                )

                rows = result.fetchall()
                return [
                    UserSearchPattern(
                        query_text=row.query_text,
                        search_count=row.search_count,
                        engines_used=row.engines_used,
                        avg_quality_score=row.avg_quality_score,
                        first_searched=row.first_searched,
                        last_searched=row.last_searched
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get user search patterns: {e}")
            raise

    async def get_analytics_summary(
        self,
        period: AnalyticsPeriod = AnalyticsPeriod.ONE_WEEK
    ) -> AnalyticsSummary:
        """분석 요약 조회

        Args:
            period: 분석 기간

        Returns:
            AnalyticsSummary: 분석 요약
        """
        try:
            period_days = self._period_to_days(period)

            async with await db_manager.get_session() as session:
                # 전체 통계 조회
                result = await session.execute(
                    text("""
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
                    """),
                    {"period": f"{period_days} days"}
                )
                row = result.fetchone()

                # 가장 많이 사용된 엔진
                result = await session.execute(
                    text("""
                        SELECT engine_name, COUNT(*) as cnt
                        FROM web_search_queries
                        WHERE executed_at > NOW() - :period::interval
                        GROUP BY engine_name
                        ORDER BY cnt DESC
                        LIMIT 1
                    """),
                    {"period": f"{period_days} days"}
                )
                top_engine_row = result.fetchone()

                # 가장 많이 검색된 쿼리
                result = await session.execute(
                    text("""
                        SELECT query_text, COUNT(*) as cnt
                        FROM web_search_queries
                        WHERE executed_at > NOW() - :period::interval
                        GROUP BY query_text
                        ORDER BY cnt DESC
                        LIMIT 1
                    """),
                    {"period": f"{period_days} days"}
                )
                top_query_row = result.fetchone()

                return AnalyticsSummary(
                    period=period.value,
                    total_queries=row.total_queries,
                    total_engines=row.total_engines,
                    total_users=row.total_users,
                    avg_quality_score=row.avg_quality_score,
                    success_rate=row.success_rate,
                    top_engine=top_engine_row.engine_name if top_engine_row else None,
                    top_query=top_query_row.query_text if top_query_row else None
                )

        except Exception as e:
            logger.error(f"Failed to get analytics summary: {e}")
            raise

    async def get_comprehensive_analytics(
        self,
        period: AnalyticsPeriod = AnalyticsPeriod.ONE_WEEK,
        engine_name: Optional[str] = None
    ) -> ComprehensiveAnalytics:
        """종합 분석 결과 조회

        Args:
            period: 분석 기간
            engine_name: 필터링할 엔진 이름

        Returns:
            ComprehensiveAnalytics: 종합 분석 결과
        """
        try:
            # 병렬로 여러 분석 수행
            summary = await self.get_analytics_summary(period)
            popular_queries_resp = await self.get_popular_queries(period, engine_name, 20)
            engine_stats_resp = await self.get_engine_statistics(period)
            quality_analysis = await self.get_quality_analysis(engine_name, 30)

            return ComprehensiveAnalytics(
                summary=summary,
                popular_queries=popular_queries_resp.queries,
                engine_statistics=engine_stats_resp.statistics,
                quality_analysis=quality_analysis
            )

        except Exception as e:
            logger.error(f"Failed to get comprehensive analytics: {e}")
            raise


# ============================================================================
# 글로벌 서비스 인스턴스
# ============================================================================

analytics_service = WebSearchAnalyticsService()
