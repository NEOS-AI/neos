# 웹 검색 로깅 시스템

neos의 웹 검색 로깅 시스템은 Tavily 등의 검색 엔진을 통한 검색 쿼리와 결과를 비동기적으로 데이터베이스에 저장합니다.

## 주요 기능

1. **검색 쿼리 로깅**: 검색 쿼리, 실행 시간, 검색 엔진 정보 등을 기록
2. **검색 결과 저장**: 검색 결과 URL, 제목, 내용, 점수 등을 저장
3. **시간에 따른 변화 추적**: 동일 URL의 검색 결과가 시간에 따라 어떻게 변하는지 추적
4. **비동기 저장**: 메시지 큐를 통한 비동기 저장으로 검색 성능에 영향 최소화
5. **모듈화된 구조**: 추후 Redis Pub/Sub, Kafka 등으로 쉽게 마이그레이션 가능
6. **ParadeDB BM25 인덱스**: 검색 쿼리에 대한 전문 검색 지원 (선택 사항)

## 아키텍처

```
┌─────────────────┐
│ Search Agent    │
│ (Tavily, etc.)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ WebSearchLogger │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ Message Queue   │─────▶│  PostgreSQL  │
│ (Memory/Redis)  │      │   Database   │
└─────────────────┘      └──────────────┘
```

## 데이터베이스 스키마

### 주요 테이블

#### 1. `search_engines`
검색 엔진 정보 및 통계를 관리합니다.

```sql
- engine_name: 검색 엔진 이름 (tavily, mcp_brave, etc.)
- engine_type: 엔진 타입 (web, academic, news, data)
- total_queries_executed: 실행된 총 쿼리 수
- success_rate: 성공률
```

#### 2. `web_search_queries`
검색 쿼리 실행 로그를 저장합니다.

```sql
- query_id: 고유 쿼리 ID (UUID)
- query_text: 검색 쿼리 텍스트
- query_hash: 쿼리 중복 체크용 해시
- engine_id: 검색 엔진 ID (FK)
- execution_time_ms: 실행 시간
- status: 검색 상태 (completed, failed, timeout)
```

#### 3. `web_search_results`
검색 결과 데이터를 저장하며, 시간에 따른 변화를 추적합니다.

```sql
- result_id: 결과 고유 ID (UUID)
- query_id: 쿼리 ID (FK)
- result_url: 결과 URL
- result_title: 제목
- result_content: 내용/스니펫
- result_version: 버전 번호
- is_latest_version: 최신 버전 여부
- content_hash: 내용 변화 감지용 해시
```

#### 4. `web_search_result_history`
검색 결과의 변경 이력을 기록합니다.

#### 5. `web_search_metrics`
검색 성능 및 품질 메트릭을 저장합니다.

## 사용 방법

### 1. 데이터베이스 스키마 설정

```bash
# PostgreSQL에 스키마 적용
psql -U postgres -d neos < db/web_search_log.sql
```

### 2. 환경 변수 설정

`.env` 파일에 다음 설정을 추가합니다:

```bash
# 웹 검색 로깅 설정
WEB_SEARCH_LOG_ASYNC=true  # 비동기 로깅 활성화
WEB_SEARCH_LOG_QUEUE_TYPE=memory  # 메시지 큐 타입: memory, redis, kafka

# Redis 사용 시 (선택 사항)
# WEB_SEARCH_LOG_QUEUE_TYPE=redis
# REDIS_URL=redis://localhost:6379
```

### 3. 코드에서 사용

검색 에이전트에서 자동으로 로깅이 수행됩니다:

```python
from neos.database.web_search_logger import get_search_logger
from neos.database.web_search_types import SearchLogRequest, SearchLogComplete, SearchResultItem

# 검색 시작 로그
search_logger = await get_search_logger()

log_request = SearchLogRequest(
    query_text="검색 쿼리",
    engine_name="tavily",
    user_id="user123",
    session_id="session456",
    query_language="ko",
    search_params={"max_results": 10}
)

query_id = await search_logger.log_search_start(log_request)

# 검색 수행...
results = await perform_search(query)

# 검색 완료 로그
log_complete = SearchLogComplete(
    query_id=query_id,
    results=[
        SearchResultItem(
            url="https://example.com",
            title="Example",
            content="Content...",
            score=0.95
        )
    ],
    execution_time_ms=1234,
    status=SearchQueryStatus.COMPLETED,
    quality_score=0.9
)

await search_logger.log_search_complete(log_complete)
```

## 메시지 큐 설정

### 인메모리 큐 (기본값)

개발 및 테스트에 적합합니다:

```bash
WEB_SEARCH_LOG_QUEUE_TYPE=memory
```

### Redis Pub/Sub

프로덕션 환경에 권장됩니다:

```bash
WEB_SEARCH_LOG_QUEUE_TYPE=redis
REDIS_URL=redis://localhost:6379
```

Redis 설치:
```bash
# Docker로 Redis 실행
docker run -d -p 6379:6379 redis:latest
```

### Kafka (추후 지원 예정)

대규모 시스템에 적합합니다:

```bash
WEB_SEARCH_LOG_QUEUE_TYPE=kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

## ParadeDB BM25 인덱스 설정 (선택 사항)

검색 쿼리에 대한 전문 검색을 원하는 경우, ParadeDB 확장을 설치하고 BM25 인덱스를 활성화할 수 있습니다.

### 1. ParadeDB 설치

```bash
# ParadeDB 확장 설치 (PostgreSQL 16+)
CREATE EXTENSION IF NOT EXISTS pg_search;
```

### 2. BM25 인덱스 생성

`db/web_search_log.sql` 파일에서 BM25 인덱스 생성 부분의 주석을 해제합니다:

```sql
-- 검색 쿼리에 대한 BM25 인덱스
CALL paradedb.create_bm25(
    index_name => 'search_queries_bm25_idx',
    table_name => 'web_search_queries',
    key_field => 'id',
    text_fields => paradedb.field('query_text', tokenizer => paradedb.tokenizer('default'))
);

-- 검색 결과 타이틀과 콘텐츠에 대한 BM25 인덱스
CALL paradedb.create_bm25(
    index_name => 'search_results_bm25_idx',
    table_name => 'web_search_results',
    key_field => 'id',
    text_fields => '{
        "result_title": {"tokenizer": "default"},
        "result_content": {"tokenizer": "default"}
    }'
);
```

### 3. BM25 검색 사용

```sql
-- 쿼리 텍스트 검색
SELECT * FROM search_queries_bm25_idx.search('machine learning', limit_rows => 10);

-- 검색 결과 검색
SELECT * FROM search_results_bm25_idx.search('artificial intelligence', limit_rows => 20);
```

## 데이터 조회 및 분석

### 유용한 뷰

#### 1. 검색 엔진 성능 개요
```sql
SELECT * FROM search_engine_performance;
```

#### 2. 최근 검색 쿼리
```sql
SELECT * FROM recent_search_queries LIMIT 100;
```

#### 3. URL별 최신 검색 결과
```sql
SELECT * FROM latest_search_results_by_url WHERE domain = 'example.com';
```

### 분석 쿼리 예시

#### 검색 엔진별 성능 비교
```sql
SELECT
    engine_name,
    COUNT(*) as total_queries,
    AVG(execution_time_ms) as avg_time_ms,
    AVG(quality_score) as avg_quality,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count
FROM web_search_queries
WHERE executed_at > NOW() - INTERVAL '7 days'
GROUP BY engine_name
ORDER BY total_queries DESC;
```

#### 인기 검색 쿼리
```sql
SELECT
    query_text,
    COUNT(*) as search_count,
    AVG(quality_score) as avg_quality,
    MAX(executed_at) as last_searched
FROM web_search_queries
WHERE executed_at > NOW() - INTERVAL '30 days'
GROUP BY query_text
HAVING COUNT(*) > 5
ORDER BY search_count DESC
LIMIT 50;
```

#### URL별 변경 추적
```sql
SELECT
    r.result_url,
    r.result_version,
    r.captured_at,
    COUNT(h.id) as change_count
FROM web_search_results r
LEFT JOIN web_search_result_history h ON r.result_id = h.result_id
WHERE r.result_url = 'https://example.com/article'
GROUP BY r.result_url, r.result_version, r.captured_at
ORDER BY r.captured_at DESC;
```

## 성능 최적화

### 인덱스 최적화
- 자주 조회하는 컬럼에 대한 인덱스가 이미 설정되어 있습니다
- 추가 인덱스가 필요한 경우 쿼리 패턴 분석 후 추가

### 파티셔닝 (대용량 데이터)
시간이 지나면서 데이터가 많아질 경우, 테이블 파티셔닝을 고려:

```sql
-- 월별 파티셔닝 예시
CREATE TABLE web_search_queries_2025_01 PARTITION OF web_search_queries
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
```

### 데이터 보관 정책
오래된 데이터를 아카이브하거나 삭제:

```sql
-- 1년 이상 된 데이터 삭제
DELETE FROM web_search_queries
WHERE executed_at < NOW() - INTERVAL '1 year';
```

## 트러블슈팅

### 로깅이 작동하지 않는 경우

1. 데이터베이스 연결 확인:
```python
from neos.database.connection import db_manager
health = await db_manager.health_check()
print(f"Database healthy: {health}")
```

2. 메시지 큐 상태 확인:
```python
from neos.database.web_search_logger import get_search_logger
logger = await get_search_logger()
print(f"Logger initialized: {logger.initialized}")
```

3. 로그 레벨 확인:
```bash
# .env 파일
LOG_LEVEL=DEBUG
```

### 성능 문제

1. 비동기 로깅 활성화 확인:
```bash
WEB_SEARCH_LOG_ASYNC=true
```

2. Redis 사용 고려:
```bash
WEB_SEARCH_LOG_QUEUE_TYPE=redis
```

## 참고 자료

- [PostgreSQL 공식 문서](https://www.postgresql.org/docs/)
- [ParadeDB 문서](https://docs.paradedb.com/)
- [Redis Pub/Sub](https://redis.io/docs/manual/pubsub/)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
