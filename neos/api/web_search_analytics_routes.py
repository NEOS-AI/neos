"""웹 검색 로그 분석 API 라우트"""

from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException, Path
from fastapi.responses import JSONResponse

from neos.database.web_search_analytics_service import analytics_service
from neos.database.web_search_analytics_types import (
    PopularQueriesResponse,
    EngineStatisticsResponse,
    SearchTrendsResponse,
    DailyStatistics,
    WeeklyStatistics,
    MonthlyStatistics,
    SearchQualityAnalysis,
    UserSearchPattern,
    AnalyticsSummary,
    ComprehensiveAnalytics,
    AnalyticsPeriod,
    TrendInterval
)

router = APIRouter(
    prefix="/api/v1/analytics/web-search",
    tags=["Web Search Analytics"]
)


@router.get(
    "/popular-queries",
    response_model=PopularQueriesResponse,
    summary="인기 검색 쿼리 조회",
    description="지정된 기간 동안 자주 검색된 쿼리 목록을 반환합니다."
)
async def get_popular_queries(
    period: AnalyticsPeriod = Query(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간 (1d, 7d, 30d, 90d, 365d)"
    ),
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름 (예: tavily, mcp_brave)"
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="반환할 최대 결과 수"
    )
):
    """
    ## 인기 검색 쿼리 조회

    특정 기간 동안 자주 검색된 쿼리를 반환합니다.

    ### 파라미터
    - **period**: 분석 기간 (1d/7d/30d/90d/365d)
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)
    - **limit**: 반환할 최대 쿼리 수

    ### 반환값
    - 검색 횟수가 많은 순으로 정렬된 쿼리 목록
    - 각 쿼리의 통계 (검색 횟수, 고유 사용자 수, 평균 품질 점수 등)
    """
    try:
        return await analytics_service.get_popular_queries(
            period=period,
            engine_name=engine_name,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/engine-statistics",
    response_model=EngineStatisticsResponse,
    summary="검색 엔진 통계 조회",
    description="각 검색 엔진의 성능 및 사용 통계를 반환합니다."
)
async def get_engine_statistics(
    period: AnalyticsPeriod = Query(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간 (1d, 7d, 30d, 90d, 365d)"
    )
):
    """
    ## 검색 엔진 통계 조회

    각 검색 엔진별 성능 및 사용 통계를 반환합니다.

    ### 파라미터
    - **period**: 분석 기간

    ### 반환값
    - 엔진별 통계 (총 쿼리 수, 성공률, 평균 응답 시간, 품질 점수 등)
    """
    try:
        return await analytics_service.get_engine_statistics(period=period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/trends",
    response_model=SearchTrendsResponse,
    summary="검색 트렌드 조회",
    description="시간대별 검색 트렌드를 반환합니다."
)
async def get_search_trends(
    period: AnalyticsPeriod = Query(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간 (1d, 7d, 30d, 90d, 365d)"
    ),
    interval: TrendInterval = Query(
        default=TrendInterval.DAY,
        description="트렌드 분석 간격 (hour, day, week, month)"
    ),
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름"
    )
):
    """
    ## 검색 트렌드 조회

    시간대별 검색 트렌드를 반환합니다.

    ### 파라미터
    - **period**: 분석 기간
    - **interval**: 트렌드 간격 (시간/일/주/월)
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)

    ### 반환값
    - 시간대별 검색 횟수 및 품질 점수
    """
    try:
        return await analytics_service.get_search_trends(
            period=period,
            interval=interval,
            engine_name=engine_name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/daily-statistics",
    response_model=List[DailyStatistics],
    summary="일일 통계 조회",
    description="일일 검색 통계를 반환합니다."
)
async def get_daily_statistics(
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름"
    ),
    limit: int = Query(
        default=30,
        ge=1,
        le=365,
        description="반환할 최대 일수"
    )
):
    """
    ## 일일 통계 조회

    일일 검색 통계를 반환합니다.

    ### 파라미터
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)
    - **limit**: 반환할 최대 일수

    ### 반환값
    - 일일 검색 통계 (쿼리 수, 사용자 수, 성공률 등)
    """
    try:
        return await analytics_service.get_daily_statistics(
            engine_name=engine_name,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/weekly-statistics",
    response_model=List[WeeklyStatistics],
    summary="주간 통계 조회",
    description="주간 검색 통계를 반환합니다."
)
async def get_weekly_statistics(
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름"
    ),
    limit: int = Query(
        default=12,
        ge=1,
        le=52,
        description="반환할 최대 주수"
    )
):
    """
    ## 주간 통계 조회

    주간 검색 통계를 반환합니다.

    ### 파라미터
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)
    - **limit**: 반환할 최대 주수

    ### 반환값
    - 주간 검색 통계 (쿼리 수, 사용자 수, 성공률 등)
    """
    try:
        return await analytics_service.get_weekly_statistics(
            engine_name=engine_name,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/monthly-statistics",
    response_model=List[MonthlyStatistics],
    summary="월간 통계 조회",
    description="월간 검색 통계를 반환합니다."
)
async def get_monthly_statistics(
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름"
    ),
    limit: int = Query(
        default=12,
        ge=1,
        le=24,
        description="반환할 최대 월수"
    )
):
    """
    ## 월간 통계 조회

    월간 검색 통계를 반환합니다.

    ### 파라미터
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)
    - **limit**: 반환할 최대 월수

    ### 반환값
    - 월간 검색 통계 (쿼리 수, 사용자 수, 성공률 등)
    """
    try:
        return await analytics_service.get_monthly_statistics(
            engine_name=engine_name,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/quality-analysis",
    response_model=List[SearchQualityAnalysis],
    summary="검색 품질 분석 조회",
    description="검색 품질 분석 결과를 반환합니다."
)
async def get_quality_analysis(
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름"
    ),
    limit: int = Query(
        default=30,
        ge=1,
        le=365,
        description="반환할 최대 일수"
    )
):
    """
    ## 검색 품질 분석 조회

    검색 품질 분석 결과를 반환합니다.

    ### 파라미터
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)
    - **limit**: 반환할 최대 일수

    ### 반환값
    - 일일 품질 분석 (평균 품질 점수, 고품질/저품질 쿼리 수 등)
    """
    try:
        return await analytics_service.get_quality_analysis(
            engine_name=engine_name,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/user/{user_id}/patterns",
    response_model=List[UserSearchPattern],
    summary="사용자 검색 패턴 조회",
    description="특정 사용자의 검색 패턴을 반환합니다."
)
async def get_user_search_patterns(
    user_id: str = Path(..., description="사용자 ID"),
    period: AnalyticsPeriod = Query(
        default=AnalyticsPeriod.ONE_MONTH,
        description="분석 기간 (1d, 7d, 30d, 90d, 365d)"
    )
):
    """
    ## 사용자 검색 패턴 조회

    특정 사용자의 검색 패턴을 반환합니다.

    ### 파라미터
    - **user_id**: 사용자 ID (경로 파라미터)
    - **period**: 분석 기간

    ### 반환값
    - 사용자가 검색한 쿼리 목록 및 통계
    """
    try:
        return await analytics_service.get_user_search_patterns(
            user_id=user_id,
            period=period
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/summary",
    response_model=AnalyticsSummary,
    summary="분석 요약 조회",
    description="전체 분석 요약을 반환합니다."
)
async def get_analytics_summary(
    period: AnalyticsPeriod = Query(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간 (1d, 7d, 30d, 90d, 365d)"
    )
):
    """
    ## 분석 요약 조회

    전체 검색 로그의 요약 통계를 반환합니다.

    ### 파라미터
    - **period**: 분석 기간

    ### 반환값
    - 총 쿼리 수, 사용자 수, 성공률, 가장 많이 사용된 엔진 및 쿼리 등
    """
    try:
        return await analytics_service.get_analytics_summary(period=period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/comprehensive",
    response_model=ComprehensiveAnalytics,
    summary="종합 분석 조회",
    description="모든 분석 결과를 한 번에 반환합니다."
)
async def get_comprehensive_analytics(
    period: AnalyticsPeriod = Query(
        default=AnalyticsPeriod.ONE_WEEK,
        description="분석 기간 (1d, 7d, 30d, 90d, 365d)"
    ),
    engine_name: Optional[str] = Query(
        default=None,
        description="필터링할 검색 엔진 이름"
    )
):
    """
    ## 종합 분석 조회

    모든 분석 결과를 한 번에 반환합니다.

    ### 파라미터
    - **period**: 분석 기간
    - **engine_name**: 특정 엔진으로 필터링 (선택사항)

    ### 반환값
    - 요약 통계, 인기 쿼리, 엔진 통계, 품질 분석 등 모든 분석 결과
    """
    try:
        return await analytics_service.get_comprehensive_analytics(
            period=period,
            engine_name=engine_name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/health",
    summary="분석 API 헬스 체크",
    description="분석 API의 상태를 확인합니다."
)
async def health_check():
    """
    ## 헬스 체크

    분석 API의 상태를 확인합니다.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "web-search-analytics",
            "version": "1.0.0"
        }
    )
