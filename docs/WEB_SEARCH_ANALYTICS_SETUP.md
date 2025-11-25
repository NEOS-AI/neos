# 웹 검색 로그 분석 API 설정 가이드

이 가이드는 웹 검색 로그 분석 API를 설정하고 사용하는 방법을 설명합니다.

## 개요

웹 검색 분석 API는 다음 기능을 제공합니다:
- ✅ 엔진별 자주 검색한 쿼리 통계 (1일/1주/1달/3개월/1년)
- ✅ 검색 엔진별 성능 및 사용 통계
- ✅ 시간대별 검색 트렌드 분석
- ✅ 검색 품질 분석
- ✅ 사용자별 검색 패턴 분석
- ✅ 일일/주간/월간 통계

## 설치 단계

### 1. 기본 검색 로그 스키마 적용 (선행 작업)

먼저 기본 검색 로그 스키마가 적용되어 있어야 합니다:

```bash
psql -U postgres -d neos -f db/web_search_log.sql
```

### 2. 분석 스키마 적용

분석용 함수 및 뷰를 추가합니다:

```bash
psql -U postgres -d neos -f db/web_search_analytics.sql
```

### 3. 스키마 확인

정상적으로 적용되었는지 확인:

```sql
-- 함수 확인
\df get_popular_queries
\df get_engine_statistics
\df get_search_trends

-- 뷰 확인
\dv daily_search_statistics
\dv weekly_search_statistics
\dv monthly_search_statistics
\dv popular_queries_7d
```

## FastAPI에 라우트 추가

### main.py 또는 routes.py에 추가

```python
from fastapi import FastAPI
from neos.api.web_search_analytics_routes import router as analytics_router

app = FastAPI()

# 분석 API 라우트 추가
app.include_router(analytics_router)
```

## API 사용 예시

### 1. 서버 실행

```bash
# uvicorn 사용
uvicorn neos.main:app --reload --port 8518

# 또는 프로젝트 방식대로
python -m neos.main
```

### 2. API 테스트

#### 인기 검색어 조회 (기본 - 7일)

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/popular-queries"
```

#### 특정 엔진의 30일간 인기 검색어

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/popular-queries?period=30d&engine_name=tavily&limit=20"
```

#### 검색 엔진별 통계

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/engine-statistics?period=7d"
```

#### 일별 트렌드

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/trends?period=30d&interval=day"
```

#### 시간별 트렌드 (특정 엔진)

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/trends?period=7d&interval=hour&engine_name=tavily"
```

#### 분석 요약

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/summary?period=7d"
```

#### 종합 분석 (한 번에 모든 데이터)

```bash
curl "http://localhost:8518/api/v1/analytics/web-search/comprehensive?period=7d"
```

## Python에서 직접 사용

API 서버 없이 Python에서 직접 사용할 수도 있습니다:

```python
import asyncio
from neos.database.web_search_analytics_service import analytics_service
from neos.database.web_search_analytics_types import AnalyticsPeriod, TrendInterval

async def main():
    # 인기 검색어 조회
    popular = await analytics_service.get_popular_queries(
        period=AnalyticsPeriod.ONE_WEEK,
        engine_name="tavily",
        limit=20
    )

    for query in popular.queries:
        print(f"{query.query_text}: {query.search_count}회 검색")

    # 엔진 통계
    engines = await analytics_service.get_engine_statistics(
        period=AnalyticsPeriod.ONE_MONTH
    )

    for stat in engines.statistics:
        print(f"{stat.engine_name}: {stat.total_queries}개 쿼리, "
              f"성공률 {stat.success_rate:.2%}")

    # 검색 트렌드
    trends = await analytics_service.get_search_trends(
        period=AnalyticsPeriod.ONE_WEEK,
        interval=TrendInterval.DAY
    )

    for trend in trends.trends:
        print(f"{trend.time_bucket}: {trend.search_count}회 검색")

asyncio.run(main())
```

## 응답 예시

### 인기 검색어

```json
{
  "period": "7d",
  "engine_name": "tavily",
  "total_count": 25,
  "queries": [
    {
      "query_text": "Python 프로그래밍",
      "search_count": 156,
      "unique_users": 45,
      "avg_quality_score": 0.92,
      "avg_execution_time_ms": 1234.56,
      "success_rate": 0.98,
      "first_searched": "2025-10-04T10:00:00Z",
      "last_searched": "2025-10-11T15:30:00Z",
      "engine_name": "tavily"
    }
  ]
}
```

### 검색 엔진 통계

```json
{
  "period": "7d",
  "total_engines": 3,
  "statistics": [
    {
      "engine_name": "tavily",
      "total_queries": 1234,
      "unique_queries": 567,
      "unique_users": 89,
      "avg_execution_time_ms": 1200.5,
      "avg_quality_score": 0.91,
      "avg_results_count": 8.5,
      "success_rate": 0.97,
      "failed_queries": 12,
      "timeout_queries": 3
    }
  ]
}
```

## 대시보드 구축 예시

### Streamlit 대시보드

```python
import streamlit as st
import asyncio
from neos.database.web_search_analytics_service import analytics_service
from neos.database.web_search_analytics_types import AnalyticsPeriod

st.title("웹 검색 분석 대시보드")

# 기간 선택
period = st.selectbox(
    "분석 기간",
    ["1d", "7d", "30d", "90d", "365d"]
)

async def load_data(period_str):
    period_map = {
        "1d": AnalyticsPeriod.ONE_DAY,
        "7d": AnalyticsPeriod.ONE_WEEK,
        "30d": AnalyticsPeriod.ONE_MONTH,
        "90d": AnalyticsPeriod.THREE_MONTHS,
        "365d": AnalyticsPeriod.ONE_YEAR
    }

    period_enum = period_map[period_str]

    # 데이터 로드
    summary = await analytics_service.get_analytics_summary(period_enum)
    popular = await analytics_service.get_popular_queries(period_enum, limit=10)
    engines = await analytics_service.get_engine_statistics(period_enum)

    return summary, popular, engines

# 데이터 로드
summary, popular, engines = asyncio.run(load_data(period))

# 요약 통계 표시
col1, col2, col3, col4 = st.columns(4)
col1.metric("총 쿼리", summary.total_queries)
col2.metric("사용자", summary.total_users)
col3.metric("엔진", summary.total_engines)
col4.metric("성공률", f"{summary.success_rate:.1%}")

# 인기 검색어
st.subheader("인기 검색어")
for query in popular.queries:
    st.write(f"**{query.query_text}** - {query.search_count}회 검색")

# 엔진 통계
st.subheader("검색 엔진 통계")
for stat in engines.statistics:
    st.write(f"**{stat.engine_name}**: {stat.total_queries}개 쿼리, "
             f"성공률 {stat.success_rate:.2%}")
```

### Grafana 연동

PostgreSQL을 데이터 소스로 추가하고 다음 쿼리 사용:

```sql
-- 인기 검색어 (7일)
SELECT * FROM popular_queries_7d LIMIT 20;

-- 일일 통계
SELECT * FROM daily_search_statistics
WHERE search_date >= NOW() - INTERVAL '30 days'
ORDER BY search_date;

-- 검색 엔진 성능
SELECT * FROM search_engine_performance;
```

## 성능 최적화

### 1. 인덱스 확인

```sql
-- 인덱스 목록 확인
SELECT * FROM pg_indexes
WHERE tablename = 'web_search_queries';

-- 인덱스 사용 확인
EXPLAIN ANALYZE
SELECT * FROM get_popular_queries('tavily', 7, 50);
```

### 2. 쿼리 성능 분석

```sql
-- 느린 쿼리 찾기
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
WHERE query LIKE '%web_search%'
ORDER BY total_time DESC
LIMIT 10;
```

### 3. 캐싱 추가

Redis를 사용한 캐싱:

```python
import redis
import json
from functools import wraps

redis_client = redis.Redis(host='localhost', port=6379, db=0)

def cache_result(ttl=300):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 캐시 키 생성
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            # 캐시 확인
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

            # 결과 생성
            result = await func(*args, **kwargs)

            # 캐시 저장
            redis_client.setex(
                cache_key,
                ttl,
                json.dumps(result, default=str)
            )

            return result
        return wrapper
    return decorator

# 사용
@cache_result(ttl=300)  # 5분 캐싱
async def get_cached_popular_queries(period):
    return await analytics_service.get_popular_queries(period)
```

## 문제 해결

### 데이터가 표시되지 않는 경우

1. 검색 로그 데이터 확인:
```sql
SELECT COUNT(*) FROM web_search_queries;
```

2. 데이터가 없으면 검색 로그 생성:
```python
# 웹 검색을 먼저 수행하여 로그 생성
from neos.agents.search_agents.realtime_data_search import RealtimeDataSearchAgent

agent = RealtimeDataSearchAgent()
result = await agent.execute("test query")
```

3. 스키마 재적용:
```bash
psql -U postgres -d neos -f db/web_search_analytics.sql
```

### 성능 문제

1. 데이터 파티셔닝:
```sql
-- 월별 파티셔닝
CREATE TABLE web_search_queries_2025_10
PARTITION OF web_search_queries
FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
```

2. 오래된 데이터 아카이브:
```sql
-- 1년 이상 된 데이터를 아카이브 테이블로 이동
INSERT INTO web_search_queries_archive
SELECT * FROM web_search_queries
WHERE executed_at < NOW() - INTERVAL '1 year';

DELETE FROM web_search_queries
WHERE executed_at < NOW() - INTERVAL '1 year';
```

## 추가 기능 개발

### 1. 알람 설정

```python
async def check_quality_alert():
    summary = await analytics_service.get_analytics_summary(
        AnalyticsPeriod.ONE_DAY
    )

    if summary.avg_quality_score < 0.7:
        send_alert(f"품질 점수 하락: {summary.avg_quality_score:.2f}")

    if summary.success_rate < 0.9:
        send_alert(f"성공률 하락: {summary.success_rate:.2%}")
```

### 2. 자동 리포트

```python
import schedule

async def generate_weekly_report():
    comprehensive = await analytics_service.get_comprehensive_analytics(
        period=AnalyticsPeriod.ONE_WEEK
    )

    # 리포트 생성
    report = create_report(comprehensive)

    # 이메일 발송
    send_email(report)

# 매주 월요일 9시 실행
schedule.every().monday.at("09:00").do(generate_weekly_report)
```

## API 문서

자세한 API 문서는 다음을 참조하세요:
- [API 문서](docs/WEB_SEARCH_ANALYTICS_API.md)
- [검색 로깅 문서](docs/WEB_SEARCH_LOGGING.md)

## Swagger UI

서버 실행 후 다음 URL에서 자동 생성된 API 문서를 확인할 수 있습니다:

```
http://localhost:8518/docs
```

또는 ReDoc:

```
http://localhost:8518/redoc
```

## 참고 자료

- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [PostgreSQL 함수](https://www.postgresql.org/docs/current/sql-createfunction.html)
- [Pydantic 모델](https://docs.pydantic.dev/)
