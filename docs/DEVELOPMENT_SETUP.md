# Development Setup Guide

이 가이드는 Neos Workflow System의 로컬 개발 환경 설정 방법을 설명합니다.

## Prerequisites

- Docker & Docker Compose
- Python 3.11+
- PostgreSQL 16 (또는 Docker 사용)
- Redis (또는 Docker 사용)

## Quick Start

### 1. 기본 인프라 시작 (Jaeger, Redis, PostgreSQL)

```bash
# Jaeger, Redis, PostgreSQL 시작
docker-compose -f docker-compose.dev.yml up -d jaeger redis postgres

# 상태 확인
docker-compose -f docker-compose.dev.yml ps

# 로그 확인
docker-compose -f docker-compose.dev.yml logs -f
```

### 2. 서비스 접근

- **Jaeger UI**: http://localhost:16686
  - 분산 추적 시각화
  - 워크플로우 성능 분석
  - 병목 지점 식별

- **PostgreSQL**: localhost:5432
  - Database: neos_db
  - User: neos
  - Password: neos_password

- **Redis**: localhost:6379

### 3. 설정 파일 준비

비밀과 credential-bearing URL은 `.env`에 두고, non-secret runtime 설정은
`config/neos.local.yaml`에 둡니다.

```bash
cp .env.template .env
cp config/neos.example.yaml config/neos.local.yaml
```

`.env`:

```dotenv
NEOS_ENV=development
NEOS_CONFIG_PATH=config/neos.local.yaml

# Database (Docker 사용 시)
DATABASE_URL=postgresql+asyncpg://neos:neos_password@localhost:5432/neos_db

# Redis (Docker 사용 시)
REDIS_URL=redis://localhost:6379/0
```

`config/neos.local.yaml`:

```yaml
telemetry:
  otel:
    enabled: true
    exporter_jaeger_endpoint: http://localhost:4318/v1/traces
    service_name: neos-workflow
    service_version: 0.19.0
    deployment_environment: development
```

### 4. Python 애플리케이션 시작

```bash
# 의존성 설치
pip install -r requirements.txt

# OpenTelemetry 패키지 설치
pip install opentelemetry-api opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-http \
    opentelemetry-instrumentation-fastapi \
    opentelemetry-instrumentation-sqlalchemy \
    opentelemetry-instrumentation-redis \
    opentelemetry-instrumentation-httpx

# 애플리케이션 시작
python -m neos.cli.main
```

## Celery 분산 실행 (Optional)

Celery 워커를 사용하여 에이전트를 분산 실행할 수 있습니다.

```bash
# Celery 워커 및 모니터링 도구 시작
docker-compose -f docker-compose.dev.yml --profile celery up -d

# Flower UI 접근
# http://localhost:5555
```

### Celery 서비스

- **celery-worker**: 분산 태스크 실행
- **celery-beat**: 스케줄된 태스크 관리
- **flower**: 웹 기반 모니터링 UI

## HNSW Index Migration

pgvector 인덱스를 IVFFlat에서 HNSW로 업그레이드합니다.

```bash
# 마이그레이션 실행
psql postgresql://neos:neos_password@localhost:5432/neos_db \
    -f db/migrations/005_upgrade_to_hnsw.sql

# 성능 벤치마크
python scripts/benchmark_hnsw.py --queries 100

# 여러 ef_search 값 비교
python scripts/benchmark_hnsw.py --compare --ef-search "20,40,80,100"
```

### 예상 성능 향상

- Query Latency: 10ms → 3-5ms (50-70% 개선)
- Recall Rate: >95% (ef_search=40)
- Index Build Time: 2-5분 (데이터 크기에 따라)

## OpenTelemetry Tracing

### Tracing 활성화

애플리케이션 시작 시 자동으로 OpenTelemetry가 초기화됩니다.

```python
from neos.workflow.telemetry import setup_telemetry, instrument_app

# 애플리케이션 초기화 시
setup_telemetry()
instrument_app(app)  # FastAPI app
```

### 커스텀 Span 생성

```python
from neos.workflow.telemetry import trace_workflow_node, trace_agent_execution

# 워크플로우 노드 추적
with trace_workflow_node("query_classifier", workflow_id="abc123"):
    result = classify_query(query)

# 에이전트 실행 추적
with trace_agent_execution("search_agent", workflow_id="abc123"):
    result = await search_agent.execute(query)
```

### Jaeger UI 사용법

1. http://localhost:16686 접속
2. Service 드롭다운에서 `neos-workflow` 선택
3. "Find Traces" 클릭하여 최근 추적 확인
4. Trace를 클릭하여 상세 타임라인 및 span 정보 확인

## Troubleshooting

### Jaeger에 trace가 표시되지 않음

```bash
# Jaeger 로그 확인
docker-compose -f docker-compose.dev.yml logs jaeger

# OTEL_ENABLED 확인
echo $OTEL_ENABLED  # true여야 함

# 엔드포인트 접근 테스트
curl http://localhost:4318/v1/traces
```

### PostgreSQL 연결 실패

```bash
# PostgreSQL 상태 확인
docker-compose -f docker-compose.dev.yml ps postgres

# 연결 테스트
psql postgresql://neos:neos_password@localhost:5432/neos_db -c "SELECT version();"

# pgvector 확장 확인
psql postgresql://neos:neos_password@localhost:5432/neos_db \
    -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

### Redis 연결 실패

```bash
# Redis 상태 확인
docker-compose -f docker-compose.dev.yml ps redis

# 연결 테스트
redis-cli -h localhost -p 6379 ping
```

## Cleanup

```bash
# 모든 서비스 중지
docker-compose -f docker-compose.dev.yml down

# 데이터 볼륨 포함 삭제 (주의!)
docker-compose -f docker-compose.dev.yml down -v
```

## Next Steps

- [Workflow Improvements](WORKFLOW_IMPROVEMENTS_IMPLEMENTATION.md) - Phase 1, 2, 3 구현 내역
- [Quick Reference](QUICK_REFERENCE_IMPROVEMENTS.md) - 개선 사항 빠른 참조
