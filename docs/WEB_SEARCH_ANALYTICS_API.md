# 웹 검색 로그 분석 API

neos의 웹 검색 로그 분석 API는 검색 엔진별 통계, 인기 검색어, 트렌드 등 다양한 분석 데이터를 제공합니다.

## 개요

- **Base URL**: `/api/v1/analytics/web-search`
- **인증**: 필요 시 설정
- **응답 형식**: JSON

## API 엔드포인트

### 1. 인기 검색 쿼리 조회

자주 검색된 쿼리 목록을 반환합니다.

```http
GET /api/v1/analytics/web-search/popular-queries
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| period | string | 아니오 | 7d | 분석 기간 (1d, 7d, 30d, 90d, 365d) |
| engine_name | string | 아니오 | null | 필터링할 엔진 이름 |
| limit | integer | 아니오 | 50 | 최대 결과 수 (1-500) |

#### 응답 예시

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

#### cURL 예시

```bash
# 기본 조회
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/popular-queries"

# 특정 엔진의 30일간 인기 쿼리
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/popular-queries?period=30d&engine_name=tavily&limit=20"
```

---

### 2. 검색 엔진 통계 조회

각 검색 엔진의 성능 및 사용 통계를 반환합니다.

```http
GET /api/v1/analytics/web-search/engine-statistics
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| period | string | 아니오 | 7d | 분석 기간 |

#### 응답 예시

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

#### cURL 예시

```bash
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/engine-statistics?period=30d"
```

---

### 3. 검색 트렌드 조회

시간대별 검색 트렌드를 반환합니다.

```http
GET /api/v1/analytics/web-search/trends
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| period | string | 아니오 | 7d | 분석 기간 |
| interval | string | 아니오 | day | 트렌드 간격 (hour, day, week, month) |
| engine_name | string | 아니오 | null | 필터링할 엔진 이름 |

#### 응답 예시

```json
{
  "period": "7d",
  "interval": "day",
  "engine_name": null,
  "trends": [
    {
      "time_bucket": "2025-10-11T00:00:00Z",
      "search_count": 234,
      "unique_queries": 156,
      "avg_quality_score": 0.89,
      "engine_name": "tavily"
    }
  ]
}
```

#### cURL 예시

```bash
# 일별 트렌드
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/trends?period=30d&interval=day"

# 시간별 트렌드 (특정 엔진)
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/trends?period=7d&interval=hour&engine_name=tavily"
```

---

### 4. 일일/주간/월간 통계 조회

#### 일일 통계

```http
GET /api/v1/analytics/web-search/daily-statistics
```

#### 주간 통계

```http
GET /api/v1/analytics/web-search/weekly-statistics
```

#### 월간 통계

```http
GET /api/v1/analytics/web-search/monthly-statistics
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| engine_name | string | 아니오 | null | 필터링할 엔진 이름 |
| limit | integer | 아니오 | 30/12/12 | 반환할 최대 개수 |

#### 응답 예시 (일일 통계)

```json
[
  {
    "search_date": "2025-10-11",
    "engine_name": "tavily",
    "total_queries": 345,
    "unique_queries": 234,
    "unique_users": 67,
    "avg_execution_time_ms": 1234.56,
    "avg_quality_score": 0.91,
    "successful_queries": 337,
    "failed_queries": 5,
    "timeout_queries": 3
  }
]
```

#### cURL 예시

```bash
# 일일 통계
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/daily-statistics?limit=30"

# 주간 통계 (특정 엔진)
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/weekly-statistics?engine_name=tavily&limit=12"

# 월간 통계
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/monthly-statistics?limit=12"
```

---

### 5. 검색 품질 분석 조회

검색 품질 분석 결과를 반환합니다.

```http
GET /api/v1/analytics/web-search/quality-analysis
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| engine_name | string | 아니오 | null | 필터링할 엔진 이름 |
| limit | integer | 아니오 | 30 | 반환할 최대 일수 |

#### 응답 예시

```json
[
  {
    "engine_name": "tavily",
    "search_date": "2025-10-11",
    "total_queries": 345,
    "avg_quality_score": 0.91,
    "avg_results_count": 8.5,
    "avg_execution_time_ms": 1234.56,
    "high_quality_queries": 290,
    "low_quality_queries": 12
  }
]
```

---

### 6. 사용자 검색 패턴 조회

특정 사용자의 검색 패턴을 반환합니다.

```http
GET /api/v1/analytics/web-search/user/{user_id}/patterns
```

#### 경로 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| user_id | string | 예 | 사용자 ID |

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| period | string | 아니오 | 30d | 분석 기간 |

#### 응답 예시

```json
[
  {
    "query_text": "Python 튜토리얼",
    "search_count": 5,
    "engines_used": ["tavily", "mcp_brave"],
    "avg_quality_score": 0.92,
    "first_searched": "2025-10-01T10:00:00Z",
    "last_searched": "2025-10-10T15:30:00Z"
  }
]
```

#### cURL 예시

```bash
curl -X GET "http://localhost:8000/api/v1/analytics/web-search/user/user123/patterns?period=30d"
```

---

### 7. 분석 요약 조회

전체 분석 요약을 반환합니다.

```http
GET /api/v1/analytics/web-search/summary
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| period | string | 아니오 | 7d | 분석 기간 |

#### 응답 예시

```json
{
  "period": "7d",
  "total_queries": 5678,
  "total_engines": 3,
  "total_users": 234,
  "avg_quality_score": 0.89,
  "success_rate": 0.96,
  "top_engine": "tavily",
  "top_query": "Python 프로그래밍"
}
```

---

### 8. 종합 분석 조회

모든 분석 결과를 한 번에 반환합니다.

```http
GET /api/v1/analytics/web-search/comprehensive
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|-------|------|
| period | string | 아니오 | 7d | 분석 기간 |
| engine_name | string | 아니오 | null | 필터링할 엔진 이름 |

#### 응답 예시

```json
{
  "summary": {
    "period": "7d",
    "total_queries": 5678,
    "total_engines": 3,
    "total_users": 234,
    "avg_quality_score": 0.89,
    "success_rate": 0.96,
    "top_engine": "tavily",
    "top_query": "Python 프로그래밍"
  },
  "popular_queries": [...],
  "engine_statistics": [...],
  "quality_analysis": [...]
}
```

---

### 9. 헬스 체크

API 상태를 확인합니다.

```http
GET /api/v1/analytics/web-search/health
```

#### 응답 예시

```json
{
  "status": "healthy",
  "service": "web-search-analytics",
  "version": "1.0.0"
}
```

## 에러 응답

모든 엔드포인트는 표준 HTTP 상태 코드를 반환합니다.

### 에러 형식

```json
{
  "detail": "에러 메시지"
}
```

### 상태 코드

- `200`: 성공
- `400`: 잘못된 요청
- `404`: 리소스를 찾을 수 없음
- `500`: 서버 내부 에러

## Python 클라이언트 예시

```python
import requests

BASE_URL = "http://localhost:8000/api/v1/analytics/web-search"

# 인기 검색어 조회
response = requests.get(
    f"{BASE_URL}/popular-queries",
    params={
        "period": "7d",
        "engine_name": "tavily",
        "limit": 20
    }
)
popular_queries = response.json()

# 엔진 통계 조회
response = requests.get(
    f"{BASE_URL}/engine-statistics",
    params={"period": "30d"}
)
engine_stats = response.json()

# 트렌드 조회
response = requests.get(
    f"{BASE_URL}/trends",
    params={
        "period": "7d",
        "interval": "day"
    }
)
trends = response.json()
```

## JavaScript/TypeScript 클라이언트 예시

```typescript
const BASE_URL = "http://localhost:8000/api/v1/analytics/web-search";

// 인기 검색어 조회
const popularQueries = await fetch(
  `${BASE_URL}/popular-queries?period=7d&engine_name=tavily&limit=20`
).then(res => res.json());

// 엔진 통계 조회
const engineStats = await fetch(
  `${BASE_URL}/engine-statistics?period=30d`
).then(res => res.json());

// 종합 분석 조회
const comprehensive = await fetch(
  `${BASE_URL}/comprehensive?period=7d`
).then(res => res.json());
```

## 사용 예시

### 대시보드 구축

```python
import asyncio
from neos.database.web_search_analytics_service import analytics_service
from neos.database.web_search_analytics_types import AnalyticsPeriod

async def build_dashboard():
    # 요약 통계
    summary = await analytics_service.get_analytics_summary(
        period=AnalyticsPeriod.ONE_WEEK
    )

    # 인기 검색어
    popular = await analytics_service.get_popular_queries(
        period=AnalyticsPeriod.ONE_WEEK,
        limit=10
    )

    # 엔진 통계
    engines = await analytics_service.get_engine_statistics(
        period=AnalyticsPeriod.ONE_WEEK
    )

    return {
        "summary": summary,
        "popular_queries": popular.queries,
        "engine_stats": engines.statistics
    }

# 실행
dashboard_data = asyncio.run(build_dashboard())
```

## 성능 최적화

1. **캐싱**: 자주 조회되는 통계는 Redis 등에 캐싱
2. **페이지네이션**: limit 파라미터 활용
3. **인덱스**: SQL 인덱스가 자동으로 생성됨
4. **비동기 처리**: 모든 API는 비동기로 처리됨

## 문제 해결

### 데이터가 없는 경우

```bash
# 분석 SQL 스키마 적용 확인
psql -U postgres -d neos -f db/web_search_analytics.sql
```

### 성능 문제

```sql
-- 인덱스 확인
SELECT * FROM pg_indexes WHERE tablename = 'web_search_queries';

-- 쿼리 성능 분석
EXPLAIN ANALYZE SELECT * FROM get_popular_queries('tavily', 7, 50);
```

## 다음 단계

1. Grafana/Metabase 등으로 대시보드 구축
2. 알람 설정 (품질 저하, 에러 증가 등)
3. 자동화된 리포트 생성
4. A/B 테스트 지원

## 참고 자료

- [웹 검색 로깅 문서](WEB_SEARCH_LOGGING.md)
- [설치 가이드](../INSTALL_WEB_SEARCH_LOGGING.md)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
