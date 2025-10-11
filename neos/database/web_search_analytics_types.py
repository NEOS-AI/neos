"""웹 검색 로그 분석 데이터 타입 정의"""

from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class AnalyticsPeriod(str, Enum):
    """분석 기간"""
    ONE_DAY = "1d"
    ONE_WEEK = "7d"
    ONE_MONTH = "30d"
    THREE_MONTHS = "90d"
    ONE_YEAR = "365d"


class TrendInterval(str, Enum):
    """트렌드 분석 간격"""
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


# ============================================================================
# Response Models
# ============================================================================

class PopularQuery(BaseModel):
    """인기 검색 쿼리"""
    query_text: str = Field(..., description="검색 쿼리 텍스트")
    search_count: int = Field(..., description="검색 횟수")
    unique_users: int = Field(..., description="고유 사용자 수")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    avg_execution_time_ms: Optional[float] = Field(None, description="평균 실행 시간 (ms)")
    success_rate: float = Field(..., description="성공률")
    first_searched: datetime = Field(..., description="첫 검색 시간")
    last_searched: datetime = Field(..., description="마지막 검색 시간")
    engine_name: str = Field(..., description="검색 엔진 이름")

    class Config:
        from_attributes = True


class EngineStatistics(BaseModel):
    """검색 엔진 통계"""
    engine_name: str = Field(..., description="검색 엔진 이름")
    total_queries: int = Field(..., description="총 쿼리 수")
    unique_queries: int = Field(..., description="고유 쿼리 수")
    unique_users: int = Field(..., description="고유 사용자 수")
    avg_execution_time_ms: Optional[float] = Field(None, description="평균 실행 시간 (ms)")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    avg_results_count: Optional[float] = Field(None, description="평균 결과 수")
    success_rate: float = Field(..., description="성공률")
    failed_queries: int = Field(..., description="실패 쿼리 수")
    timeout_queries: int = Field(..., description="타임아웃 쿼리 수")

    class Config:
        from_attributes = True


class SearchTrend(BaseModel):
    """검색 트렌드"""
    time_bucket: datetime = Field(..., description="시간 버킷")
    search_count: int = Field(..., description="검색 횟수")
    unique_queries: int = Field(..., description="고유 쿼리 수")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    engine_name: str = Field(..., description="검색 엔진 이름")

    class Config:
        from_attributes = True


class DailyStatistics(BaseModel):
    """일일 통계"""
    search_date: date = Field(..., description="검색 날짜")
    engine_name: str = Field(..., description="검색 엔진 이름")
    total_queries: int = Field(..., description="총 쿼리 수")
    unique_queries: int = Field(..., description="고유 쿼리 수")
    unique_users: int = Field(..., description="고유 사용자 수")
    avg_execution_time_ms: Optional[float] = Field(None, description="평균 실행 시간 (ms)")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    successful_queries: int = Field(..., description="성공 쿼리 수")
    failed_queries: int = Field(..., description="실패 쿼리 수")
    timeout_queries: int = Field(..., description="타임아웃 쿼리 수")

    class Config:
        from_attributes = True


class WeeklyStatistics(BaseModel):
    """주간 통계"""
    week_start: date = Field(..., description="주 시작 날짜")
    engine_name: str = Field(..., description="검색 엔진 이름")
    total_queries: int = Field(..., description="총 쿼리 수")
    unique_queries: int = Field(..., description="고유 쿼리 수")
    unique_users: int = Field(..., description="고유 사용자 수")
    avg_execution_time_ms: Optional[float] = Field(None, description="평균 실행 시간 (ms)")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    successful_queries: int = Field(..., description="성공 쿼리 수")
    failed_queries: int = Field(..., description="실패 쿼리 수")

    class Config:
        from_attributes = True


class MonthlyStatistics(BaseModel):
    """월간 통계"""
    month_start: date = Field(..., description="월 시작 날짜")
    engine_name: str = Field(..., description="검색 엔진 이름")
    total_queries: int = Field(..., description="총 쿼리 수")
    unique_queries: int = Field(..., description="고유 쿼리 수")
    unique_users: int = Field(..., description="고유 사용자 수")
    avg_execution_time_ms: Optional[float] = Field(None, description="평균 실행 시간 (ms)")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    successful_queries: int = Field(..., description="성공 쿼리 수")
    failed_queries: int = Field(..., description="실패 쿼리 수")

    class Config:
        from_attributes = True


class SearchQualityAnalysis(BaseModel):
    """검색 품질 분석"""
    engine_name: str = Field(..., description="검색 엔진 이름")
    search_date: date = Field(..., description="검색 날짜")
    total_queries: int = Field(..., description="총 쿼리 수")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    avg_results_count: Optional[float] = Field(None, description="평균 결과 수")
    avg_execution_time_ms: Optional[float] = Field(None, description="평균 실행 시간 (ms)")
    high_quality_queries: int = Field(..., description="고품질 쿼리 수 (0.8 이상)")
    low_quality_queries: int = Field(..., description="저품질 쿼리 수 (0.5 미만)")

    class Config:
        from_attributes = True


class UserActivity(BaseModel):
    """사용자 활동 분석"""
    user_id: str = Field(..., description="사용자 ID")
    total_searches: int = Field(..., description="총 검색 수")
    unique_queries: int = Field(..., description="고유 쿼리 수")
    engines_used: int = Field(..., description="사용한 엔진 수")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    first_search: datetime = Field(..., description="첫 검색 시간")
    last_search: datetime = Field(..., description="마지막 검색 시간")
    active_days: int = Field(..., description="활동 일수")

    class Config:
        from_attributes = True


class UserSearchPattern(BaseModel):
    """사용자 검색 패턴"""
    query_text: str = Field(..., description="검색 쿼리 텍스트")
    search_count: int = Field(..., description="검색 횟수")
    engines_used: List[str] = Field(..., description="사용한 엔진 목록")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    first_searched: datetime = Field(..., description="첫 검색 시간")
    last_searched: datetime = Field(..., description="마지막 검색 시간")

    class Config:
        from_attributes = True


class SimilarQuery(BaseModel):
    """유사 쿼리"""
    query_text: str = Field(..., description="검색 쿼리 텍스트")
    query_hash: str = Field(..., description="쿼리 해시")
    search_count: int = Field(..., description="검색 횟수")
    last_searched: datetime = Field(..., description="마지막 검색 시간")

    class Config:
        from_attributes = True


# ============================================================================
# Aggregated Response Models
# ============================================================================

class PopularQueriesResponse(BaseModel):
    """인기 검색 쿼리 응답"""
    period: str = Field(..., description="분석 기간")
    engine_name: Optional[str] = Field(None, description="필터링된 엔진 이름")
    total_count: int = Field(..., description="총 쿼리 수")
    queries: List[PopularQuery] = Field(..., description="인기 쿼리 목록")


class EngineStatisticsResponse(BaseModel):
    """검색 엔진 통계 응답"""
    period: str = Field(..., description="분석 기간")
    total_engines: int = Field(..., description="총 엔진 수")
    statistics: List[EngineStatistics] = Field(..., description="엔진별 통계")


class SearchTrendsResponse(BaseModel):
    """검색 트렌드 응답"""
    period: str = Field(..., description="분석 기간")
    interval: str = Field(..., description="트렌드 간격")
    engine_name: Optional[str] = Field(None, description="필터링된 엔진 이름")
    trends: List[SearchTrend] = Field(..., description="트렌드 데이터")


class AnalyticsSummary(BaseModel):
    """분석 요약"""
    period: str = Field(..., description="분석 기간")
    total_queries: int = Field(..., description="총 쿼리 수")
    total_engines: int = Field(..., description="사용된 엔진 수")
    total_users: int = Field(..., description="총 사용자 수")
    avg_quality_score: Optional[float] = Field(None, description="평균 품질 점수")
    success_rate: float = Field(..., description="성공률")
    top_engine: Optional[str] = Field(None, description="가장 많이 사용된 엔진")
    top_query: Optional[str] = Field(None, description="가장 많이 검색된 쿼리")


class ComprehensiveAnalytics(BaseModel):
    """종합 분석 결과"""
    summary: AnalyticsSummary = Field(..., description="요약 통계")
    popular_queries: List[PopularQuery] = Field(..., description="인기 검색어")
    engine_statistics: List[EngineStatistics] = Field(..., description="엔진별 통계")
    quality_analysis: List[SearchQualityAnalysis] = Field(..., description="품질 분석")


# ============================================================================
# Query Parameters
# ============================================================================

class AnalyticsQueryParams(BaseModel):
    """분석 쿼리 파라미터"""
    period: AnalyticsPeriod = Field(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간"
    )
    engine_name: Optional[str] = Field(
        None,
        description="필터링할 엔진 이름"
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="반환할 최대 결과 수"
    )


class TrendsQueryParams(BaseModel):
    """트렌드 쿼리 파라미터"""
    period: AnalyticsPeriod = Field(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간"
    )
    interval: TrendInterval = Field(
        default=TrendInterval.DAY,
        description="트렌드 분석 간격"
    )
    engine_name: Optional[str] = Field(
        None,
        description="필터링할 엔진 이름"
    )


class UserAnalyticsQueryParams(BaseModel):
    """사용자 분석 쿼리 파라미터"""
    user_id: str = Field(..., description="사용자 ID")
    period: AnalyticsPeriod = Field(
        default=AnalyticsPeriod.ONE_MONTH,
        description="분석 기간"
    )
