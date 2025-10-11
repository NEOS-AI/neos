# 웹 검색 로깅 시스템 설치 가이드

이 가이드는 neos에 웹 검색 로깅 시스템을 설치하고 설정하는 방법을 설명합니다.

## 개요

웹 검색 로깅 시스템은 다음을 제공합니다:
- Tavily 등 검색 엔진의 쿼리 및 결과를 DB에 자동 저장
- 시간에 따른 검색 결과 변화 추적
- 비동기 로깅으로 검색 성능 영향 최소화
- 메시지 큐를 통한 확장 가능한 아키텍처
- ParadeDB BM25 인덱스를 통한 전문 검색 (선택)

## 설치 단계

### 1. 데이터베이스 스키마 적용

PostgreSQL 데이터베이스에 스키마를 적용합니다:

```bash
# PostgreSQL에 접속
psql -U postgres -d neos

# 스키마 적용
\i db/web_search_log.sql
```

또는 명령줄에서:

```bash
psql -U postgres -d neos -f db/web_search_log.sql
```

### 2. 환경 변수 설정

`.env` 파일에 다음 설정을 추가합니다:

```bash
# 데이터베이스 설정 (기존)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/neos

# 웹 검색 로깅 설정
WEB_SEARCH_LOG_ASYNC=true  # 비동기 로깅 활성화
WEB_SEARCH_LOG_QUEUE_TYPE=memory  # 메시지 큐 타입
```

### 3. Python 패키지 설치 (필요시)

Redis를 사용하려면 redis 패키지를 설치합니다:

```bash
# Redis Pub/Sub 사용 시
pip install redis

# 또는 uv 사용 시
uv pip install redis
```

## 설정 옵션

### 메시지 큐 타입

#### 인메모리 큐 (기본값)

개발 및 테스트에 적합합니다:

```bash
WEB_SEARCH_LOG_ASYNC=true
WEB_SEARCH_LOG_QUEUE_TYPE=memory
```

#### Redis Pub/Sub

프로덕션 환경에 권장됩니다:

```bash
WEB_SEARCH_LOG_ASYNC=true
WEB_SEARCH_LOG_QUEUE_TYPE=redis
REDIS_URL=redis://localhost:6379
```

Redis 서버 실행:

```bash
# Docker로 Redis 실행
docker run -d -p 6379:6379 redis:latest

# 또는 로컬 설치
brew install redis  # macOS
redis-server
```

#### 동기 모드

메시지 큐 없이 직접 DB에 저장 (비권장):

```bash
WEB_SEARCH_LOG_ASYNC=false
```

## 사용 방법

### 자동 로깅

Tavily 검색 에이전트는 자동으로 로깅을 수행합니다. 별도 코드 변경 없이 바로 사용 가능합니다:

```python
# 기존 코드 그대로 사용
from neos.agents.search_agents.realtime_data_search import RealtimeDataSearchAgent

agent = RealtimeDataSearchAgent()
result = await agent.execute("검색 쿼리", context={"user_id": "user123"})
```

### 수동 로깅 (다른 검색 엔진)

새로운 검색 엔진을 추가할 때:

```python
from neos.database.web_search_logger import get_search_logger
from neos.database.web_search_types import (
    SearchLogRequest,
    SearchLogComplete,
    SearchResultItem,
    SearchQueryStatus
)

# 로거 가져오기
search_logger = await get_search_logger()

# 검색 시작 로그
log_request = SearchLogRequest(
    query_text="검색 쿼리",
    engine_name="custom_engine",
    user_id="user123",
    session_id="session456"
)
query_id = await search_logger.log_search_start(log_request)

# 검색 수행
results = await your_search_function(query)

# 검색 완료 로그
log_complete = SearchLogComplete(
    query_id=query_id,
    results=[
        SearchResultItem(
            url=result.url,
            title=result.title,
            content=result.content,
            score=result.score
        )
        for result in results
    ],
    execution_time_ms=1234,
    status=SearchQueryStatus.COMPLETED
)
await search_logger.log_search_complete(log_complete)
```

## 테스트

통합 테스트 실행:

```bash
python3 test_web_search_logging.py
```

예상 출력:
```
======================================================================
웹 검색 로깅 시스템 테스트
======================================================================

1. 메시지 큐 초기화...
   ✓ 로거 초기화 완료

2. 검색 시작 로그...
   ✓ 검색 시작 로그 생성 완료
   ...
```

## 데이터 조회

### SQL 쿼리 예시

#### 최근 검색 쿼리 조회
```sql
SELECT * FROM recent_search_queries LIMIT 10;
```

#### 검색 엔진별 성능
```sql
SELECT * FROM search_engine_performance;
```

#### 특정 쿼리의 결과
```sql
SELECT
    q.query_text,
    r.result_title,
    r.result_url,
    r.relevance_score
FROM web_search_queries q
JOIN web_search_results r ON q.query_id = r.query_id
WHERE q.query_text = '검색어'
ORDER BY r.result_position;
```

## ParadeDB BM25 인덱스 설정 (선택)

전문 검색이 필요한 경우:

### 1. ParadeDB 설치

```bash
# PostgreSQL에 ParadeDB 확장 설치
# 자세한 내용은 https://docs.paradedb.com 참조
```

### 2. BM25 인덱스 활성화

`db/web_search_log.sql` 파일에서 BM25 인덱스 관련 주석을 해제하고 다시 적용:

```sql
-- 주석 해제
CREATE EXTENSION IF NOT EXISTS pg_search;

CALL paradedb.create_bm25(
    index_name => 'search_queries_bm25_idx',
    table_name => 'web_search_queries',
    key_field => 'id',
    text_fields => paradedb.field('query_text', tokenizer => paradedb.tokenizer('default'))
);
```

### 3. BM25 검색 사용

```sql
-- 검색 쿼리 텍스트 검색
SELECT * FROM search_queries_bm25_idx.search(
    'machine learning',
    limit_rows => 10
);
```

## 트러블슈팅

### 데이터베이스 연결 실패

```python
from neos.database.connection import db_manager

# DB 헬스 체크
health = await db_manager.health_check()
print(f"Database healthy: {health}")
```

### 메시지 큐 문제

로그 레벨을 DEBUG로 변경:

```bash
# .env
LOG_LEVEL=DEBUG
```

### asyncpg 모듈 에러

asyncpg가 설치되지 않은 경우:

```bash
pip install asyncpg
# 또는
uv pip install asyncpg
```

## 성능 최적화

### 대용량 데이터 처리

1. **파티셔닝**: 월별로 테이블 파티셔닝
2. **인덱스 최적화**: 쿼리 패턴에 맞는 추가 인덱스
3. **데이터 아카이빙**: 오래된 데이터를 별도 테이블로 이동

### 메시지 큐 최적화

프로덕션 환경에서는 Redis Pub/Sub 사용 권장:

```bash
WEB_SEARCH_LOG_QUEUE_TYPE=redis
REDIS_URL=redis://localhost:6379
```

## 다음 단계

1. [웹 검색 로깅 문서](docs/WEB_SEARCH_LOGGING.md) 참조
2. 실제 검색 수행 후 데이터 확인
3. 대시보드 구축 (선택)
4. 추가 검색 엔진 통합

## 지원 및 문의

문제가 발생하면 이슈를 등록해주세요.
