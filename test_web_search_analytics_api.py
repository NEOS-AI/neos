"""웹 검색 분석 API 테스트 스크립트

API 서버가 실행 중이어야 하며, PostgreSQL에 데이터가 있어야 합니다.
"""

import asyncio
import sys

# Import 테스트
try:
    from neos.database.web_search_analytics_service import analytics_service
    from neos.database.web_search_analytics_types import (
        AnalyticsPeriod,
        TrendInterval
    )
    print("✓ 모듈 import 성공")
except Exception as e:
    print(f"✗ 모듈 import 실패: {e}")
    sys.exit(1)


async def test_analytics_service():
    """분석 서비스 테스트"""
    print("\n" + "=" * 70)
    print("웹 검색 분석 서비스 테스트")
    print("=" * 70)
    print()

    print("주의: 이 테스트는 실제 PostgreSQL 데이터베이스가 필요합니다.")
    print("데이터베이스에 검색 로그 데이터가 있어야 결과가 반환됩니다.")
    print()

    try:
        # 1. 인기 검색어 조회 테스트
        print("1. 인기 검색어 조회 테스트...")
        try:
            popular = await analytics_service.get_popular_queries(
                period=AnalyticsPeriod.ONE_WEEK,
                engine_name=None,
                limit=10
            )
            print(f"   ✓ 성공: {popular.total_count}개의 인기 검색어 조회")
            if popular.queries:
                print(f"     가장 인기있는 쿼리: {popular.queries[0].query_text}")
                print(f"     검색 횟수: {popular.queries[0].search_count}")
        except Exception as e:
            print(f"   ⚠ 에러: {e}")
        print()

        # 2. 엔진 통계 조회 테스트
        print("2. 검색 엔진 통계 조회 테스트...")
        try:
            engines = await analytics_service.get_engine_statistics(
                period=AnalyticsPeriod.ONE_WEEK
            )
            print(f"   ✓ 성공: {engines.total_engines}개 엔진의 통계 조회")
            if engines.statistics:
                for stat in engines.statistics:
                    print(f"     - {stat.engine_name}: {stat.total_queries}개 쿼리, "
                          f"성공률 {stat.success_rate:.2%}")
        except Exception as e:
            print(f"   ⚠ 에러: {e}")
        print()

        # 3. 검색 트렌드 조회 테스트
        print("3. 검색 트렌드 조회 테스트...")
        try:
            trends = await analytics_service.get_search_trends(
                period=AnalyticsPeriod.ONE_WEEK,
                interval=TrendInterval.DAY,
                engine_name=None
            )
            print(f"   ✓ 성공: {len(trends.trends)}개의 트렌드 데이터 조회")
            if trends.trends:
                latest = trends.trends[0]
                print(f"     최근 트렌드: {latest.time_bucket}")
                print(f"     검색 횟수: {latest.search_count}")
        except Exception as e:
            print(f"   ⚠ 에러: {e}")
        print()

        # 4. 분석 요약 조회 테스트
        print("4. 분석 요약 조회 테스트...")
        try:
            summary = await analytics_service.get_analytics_summary(
                period=AnalyticsPeriod.ONE_WEEK
            )
            print(f"   ✓ 성공")
            print(f"     총 쿼리 수: {summary.total_queries}")
            print(f"     사용된 엔진 수: {summary.total_engines}")
            print(f"     총 사용자 수: {summary.total_users}")
            print(f"     평균 품질 점수: {summary.avg_quality_score:.3f}" if summary.avg_quality_score else "     평균 품질 점수: N/A")
            print(f"     성공률: {summary.success_rate:.2%}")
            if summary.top_engine:
                print(f"     가장 많이 사용된 엔진: {summary.top_engine}")
            if summary.top_query:
                print(f"     가장 많이 검색된 쿼리: {summary.top_query}")
        except Exception as e:
            print(f"   ⚠ 에러: {e}")
        print()

        # 5. 일일 통계 조회 테스트
        print("5. 일일 통계 조회 테스트...")
        try:
            daily = await analytics_service.get_daily_statistics(
                engine_name=None,
                limit=7
            )
            print(f"   ✓ 성공: {len(daily)}일의 통계 조회")
            if daily:
                latest = daily[0]
                print(f"     최근 날짜: {latest.search_date}")
                print(f"     쿼리 수: {latest.total_queries}")
        except Exception as e:
            print(f"   ⚠ 에러: {e}")
        print()

        # 6. 품질 분석 조회 테스트
        print("6. 검색 품질 분석 조회 테스트...")
        try:
            quality = await analytics_service.get_quality_analysis(
                engine_name=None,
                limit=7
            )
            print(f"   ✓ 성공: {len(quality)}일의 품질 분석 조회")
            if quality:
                latest = quality[0]
                print(f"     날짜: {latest.search_date}")
                print(f"     평균 품질 점수: {latest.avg_quality_score:.3f}" if latest.avg_quality_score else "     평균 품질 점수: N/A")
                print(f"     고품질 쿼리: {latest.high_quality_queries}")
                print(f"     저품질 쿼리: {latest.low_quality_queries}")
        except Exception as e:
            print(f"   ⚠ 에러: {e}")
        print()

        print("=" * 70)
        print("테스트 완료!")
        print("=" * 70)
        print()
        print("실제 데이터가 없는 경우 에러가 발생할 수 있습니다.")
        print("검색 로그 데이터를 먼저 생성해주세요.")
        print()

    except Exception as e:
        print(f"✗ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()


def print_api_examples():
    """API 사용 예시 출력"""
    print("\n" + "=" * 70)
    print("API 엔드포인트 사용 예시")
    print("=" * 70)
    print()
    print("FastAPI 서버를 실행한 후 다음 curl 명령어로 API를 테스트할 수 있습니다:")
    print()
    print("# 인기 검색어 조회")
    print('curl "http://localhost:8000/api/v1/analytics/web-search/popular-queries?period=7d&limit=10"')
    print()
    print("# 검색 엔진 통계")
    print('curl "http://localhost:8000/api/v1/analytics/web-search/engine-statistics?period=7d"')
    print()
    print("# 검색 트렌드")
    print('curl "http://localhost:8000/api/v1/analytics/web-search/trends?period=7d&interval=day"')
    print()
    print("# 분석 요약")
    print('curl "http://localhost:8000/api/v1/analytics/web-search/summary?period=7d"')
    print()
    print("# 종합 분석")
    print('curl "http://localhost:8000/api/v1/analytics/web-search/comprehensive?period=7d"')
    print()
    print("# API 헬스 체크")
    print('curl "http://localhost:8000/api/v1/analytics/web-search/health"')
    print()


if __name__ == "__main__":
    print("\n웹 검색 분석 API 테스트")
    print()

    # 서비스 테스트
    asyncio.run(test_analytics_service())

    # API 예시 출력
    print_api_examples()

    print("문서: docs/WEB_SEARCH_ANALYTICS_API.md 참조")
    print()
