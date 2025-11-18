# NEOS CI/CD 구조 문서

> **작성일**: 2025-11-18
> **버전**: 1.0
> **상태**: Production Ready (85%)

## 목차

1. [개요](#개요)
2. [GitHub Actions 워크플로우](#github-actions-워크플로우)
3. [Docker 구성](#docker-구성)
4. [인프라 구성 요소](#인프라-구성-요소)
5. [테스팅 전략](#테스팅-전략)
6. [모니터링 및 관찰성](#모니터링-및-관찰성)
7. [배포 프로세스](#배포-프로세스)
8. [현재 상태 및 권장사항](#현재-상태-및-권장사항)

---

## 개요

NEOS는 **GitHub Actions 기반의 현대적인 CI/CD 파이프라인**을 사용하여 지속적 통합 및 배포를 자동화합니다.

### 핵심 특징

- ✅ **자동화된 테스팅**: 모든 푸시 및 PR에 대한 자동 테스트
- ✅ **보안 스캐닝**: bandit, safety를 통한 취약점 검사
- ✅ **코드 품질 검증**: black, isort, flake8, mypy
- ✅ **멀티 플랫폼 빌드**: linux/amd64, linux/arm64
- ✅ **엔터프라이즈급 모니터링**: Prometheus, Grafana, Jaeger, Loki
- ✅ **수평 확장 지원**: 로드 밸런싱 및 복제본 관리

### 기술 스택

| 카테고리 | 기술 |
|---------|------|
| CI/CD | GitHub Actions |
| 컨테이너 | Docker, Docker Compose |
| 레지스트리 | GitHub Container Registry (ghcr.io) |
| 오케스트레이션 | Docker Compose (Kubernetes 준비 중) |
| 모니터링 | Prometheus, Grafana, Loki, Jaeger |
| 로드 밸런서 | Nginx |
| 데이터베이스 | PostgreSQL 17 + pgvector |
| 캐시 | Redis |
| 메시지 큐 | RabbitMQ (Celery) |

---

## GitHub Actions 워크플로우

### 1. CI 워크플로우 (`.github/workflows/ci.yml`)

**트리거 조건**:
- `main`, `develop`, `claude/*` 브랜치에 푸시
- `main`, `develop` 브랜치로의 Pull Request

**실행 환경**:
- Python 3.12
- Node.js 20
- PostgreSQL (서비스 컨테이너)
- Redis (서비스 컨테이너)

#### Job 구조

##### 1.1 Backend Tests (`backend-tests`)

```yaml
목적: 백엔드 단위 테스트 및 통합 테스트 실행
환경: Ubuntu Latest + PostgreSQL + Redis
단계:
  1. 저장소 체크아웃
  2. Python 3.12 설정
  3. 의존성 설치 (pip)
  4. 데이터베이스 마이그레이션
  5. pytest 실행 (커버리지 측정)
  6. Codecov에 커버리지 업로드
```

**커버리지 목표**: 80%+

**테스트 마커**:
- `unit`: 단위 테스트
- `integration`: 통합 테스트
- `slow`: 느린 테스트 (선택적 실행)

##### 1.2 Security Scan (`security-scan`)

```yaml
목적: 보안 취약점 스캐닝
도구:
  - safety: 의존성 취약점 검사
  - bandit: 코드 보안 이슈 검사
```

**스캔 대상**:
- Python 패키지 의존성
- 소스 코드 보안 패턴

##### 1.3 Code Quality (`code-quality`)

```yaml
목적: 코드 품질 및 스타일 검증
도구:
  - black: 코드 포맷팅 검증
  - isort: import 정렬 검증
  - flake8: 코드 린팅
  - mypy: 타입 체킹 (현재 non-blocking)
```

##### 1.4 Docker Build (`docker-build`)

```yaml
목적: Docker 이미지 빌드 검증
특징:
  - BuildKit 캐시 사용
  - 멀티 스테이지 빌드
  - 레이어 캐싱 최적화
```

##### 1.5 Integration Tests (`integration-tests`)

```yaml
목적: Docker Compose 기반 통합 테스트
환경: 전체 스택 (backend + postgres + redis)
검증:
  - API 엔드포인트
  - 데이터베이스 연결
  - 캐시 작동
```

##### 1.6 Build Summary (`build-summary`)

```yaml
목적: 모든 Job 결과 집계
상태: 모든 Job이 성공해야 통과
```

### 2. CD 워크플로우 (`.github/workflows/cd.yml`)

**트리거 조건**:
- `main` 브랜치에 푸시 → **Staging 배포**
- `v*` 태그 푸시 → **Production 배포**
- 수동 실행 (workflow_dispatch)

**레지스트리**: GitHub Container Registry (`ghcr.io`)

#### Job 구조

##### 2.1 Build & Push (`build-and-push`)

```yaml
목적: 멀티 플랫폼 Docker 이미지 빌드 및 푸시
플랫폼:
  - linux/amd64
  - linux/arm64
기능:
  - SBOM (Software Bill of Materials) 생성
  - 이미지 서명
  - BuildKit 캐시 활용
태그 전략:
  - latest (main 브랜치)
  - {branch-name} (브랜치별)
  - {tag-name} (릴리스 태그)
  - {sha} (커밋 해시)
```

##### 2.2 Deploy to Staging (`deploy-staging`)

```yaml
조건: main 브랜치 푸시
단계:
  1. SSH 연결 설정
  2. Docker Compose로 배포
  3. 스모크 테스트 실행
  4. Slack 알림 전송
롤백: 실패 시 자동 롤백
```

##### 2.3 Deploy to Production (`deploy-production`)

```yaml
조건: v* 태그 푸시
단계:
  1. SSH 연결 설정
  2. Docker Compose로 배포
  3. 헬스 체크 실행
  4. GitHub Release 생성
  5. Slack 알림 전송
롤백: 실패 시 자동 롤백
```

##### 2.4 Database Migrations (`database-migrations`)

```yaml
도구: Alembic
단계:
  1. 마이그레이션 스크립트 검증
  2. 스키마 변경 적용
  3. 데이터 무결성 검증
```

##### 2.5 Post-Deployment Tests (`post-deployment-tests`)

```yaml
목적: 배포 후 검증
테스트:
  - API 엔드포인트 테스트
  - 성능 테스트
  - 기능 테스트
```

---

## Docker 구성

### 1. 메인 Dockerfile (`/Dockerfile`)

```dockerfile
베이스 이미지: python:3.11-slim
시스템 의존성:
  - gcc, g++ (컴파일)
  - libpq-dev (PostgreSQL)
  - curl (헬스 체크)
포트: 8518
헬스 체크: GET http://localhost:8518/health
엔트리포인트: python neos/main.py
```

**빌드 최적화**:
- 멀티 스테이지 빌드
- 레이어 캐싱
- .dockerignore 활용

### 2. PostgreSQL Dockerfile (`/docker/Dockerfile.psql`)

```dockerfile
베이스: ParadeDB (PostgreSQL 17)
확장:
  - pgvector: 벡터 검색
  - pgvectorscale: 벡터 스케일링
  - pg_search: 전문 검색
초기화: /docker-entrypoint-initdb.d/
```

### 3. Docker Compose Enterprise (`/docker-compose.enterprise.yml`)

#### 3.1 서비스 구성

##### Backend (API 서버)

```yaml
복제본: 3개
포트: 8518
환경 변수:
  - DATABASE_URL
  - REDIS_URL
  - RABBITMQ_URL
  - OPENAI_API_KEY
헬스 체크: /health 엔드포인트
리소스:
  - CPU: 2 코어
  - Memory: 4GB
```

##### PostgreSQL (데이터베이스)

```yaml
이미지: ParadeDB with pgvector
포트: 5432
볼륨: postgres-data (영구 저장)
확장:
  - pgvector
  - pgvectorscale
  - pg_search
백업: 자동 백업 스크립트
```

##### Redis (캐시)

```yaml
이미지: redis:7-alpine
포트: 6379
지속성: AOF + RDB
볼륨: redis-data
설정:
  - maxmemory: 2gb
  - maxmemory-policy: allkeys-lru
```

##### RabbitMQ (메시지 큐)

```yaml
이미지: rabbitmq:3-management
포트:
  - 5672 (AMQP)
  - 15672 (Management UI)
용도: Celery 백그라운드 작업
```

##### Nginx (로드 밸런서)

```yaml
포트: 80, 443
알고리즘: least-connections
백엔드: 3개 서버
기능:
  - Rate Limiting (60 req/min API, 5 req/min Auth)
  - WebSocket 지원
  - GZIP 압축
  - 보안 헤더
헬스 체크: /health
```

#### 3.2 모니터링 스택

##### Prometheus (메트릭 수집)

```yaml
포트: 9090
스크랩 주기: 10-30초
타겟:
  - Backend (8518/metrics)
  - PostgreSQL Exporter (9187)
  - Redis Exporter (9121)
  - RabbitMQ (15692)
알림: alerts.yml 규칙
```

##### Grafana (시각화)

```yaml
포트: 3000
데이터 소스:
  - Prometheus (기본)
  - Loki (로그)
  - Jaeger (트레이싱)
  - PostgreSQL (직접 쿼리)
대시보드:
  - 시스템 메트릭
  - API 성능
  - 워크플로우 품질
  - 데이터베이스 성능
```

##### Loki (로그 수집)

```yaml
포트: 3100
수집 대상:
  - Backend 로그
  - Nginx 액세스/에러 로그
  - PostgreSQL 로그
저장: 로컬 파일 시스템
보존: 30일
```

##### Jaeger (분산 추적)

```yaml
포트:
  - 16686 (UI)
  - 14268 (수집)
  - 6831 (Agent)
기능:
  - 요청 추적
  - 서비스 맵
  - 성능 분석
저장: 메모리 (프로덕션: Cassandra/Elasticsearch)
```

##### Exporters

**PostgreSQL Exporter**:
```yaml
포트: 9187
메트릭:
  - 연결 풀
  - 쿼리 성능
  - 테이블 크기
  - 인덱스 사용률
```

**Redis Exporter**:
```yaml
포트: 9121
메트릭:
  - 캐시 히트율
  - 메모리 사용량
  - 키 개수
  - 명령어 통계
```

---

## 인프라 구성 요소

### 1. Prometheus 설정 (`/config/prometheus.yml`)

```yaml
글로벌 설정:
  scrape_interval: 15s
  evaluation_interval: 15s

스크랩 타겟:
  - backend: 10초 주기
  - postgres: 30초 주기
  - redis: 15초 주기
  - rabbitmq: 30초 주기

알림 규칙: /config/alerts.yml
```

### 2. 알림 규칙 (`/config/alerts.yml`)

**총 17개 알림 규칙**:

#### API 성능
- `HighErrorRate`: 5분간 에러율 5% 초과
- `HighResponseTime`: P95 응답 시간 2초 초과
- `APIServiceDown`: 서비스 다운 1분 초과

#### 워크플로우
- `HighWorkflowFailureRate`: 워크플로우 실패율 20% 초과
- `LowWorkflowQualityScore`: 품질 점수 0.7 미만

#### 에이전트
- `HighAgentExecutionErrors`: 에이전트 에러 10% 초과

#### LLM
- `HighLLMCost`: 시간당 LLM 비용 $100 초과
- `HighLLMAPIErrors`: LLM API 에러율 10% 초과

#### 데이터베이스
- `HighDatabaseConnectionPool`: 연결 풀 사용률 80% 초과
- `SlowDatabaseQueries`: P95 쿼리 시간 1초 초과

#### 캐시
- `LowCacheHitRate`: 캐시 히트율 70% 미만

#### 리소스
- `HighMemoryUsage`: 메모리 사용률 90% 초과
- `HighActiveSessions`: 동시 세션 1000개 초과

### 3. Nginx 설정 (`/config/nginx.conf`)

```nginx
업스트림 설정:
  - backend1:8518
  - backend2:8518
  - backend3:8518
  - 알고리즘: least_conn

Rate Limiting:
  - API: 60 req/min
  - Auth: 5 req/min

기능:
  - WebSocket 프록시
  - GZIP 압축
  - 보안 헤더 (X-Frame-Options, CSP 등)
  - 액세스 로그
  - 에러 로그

헬스 체크:
  - /health 엔드포인트 폴링
  - 실패 시 자동 제외
```

### 4. Grafana 데이터 소스 (`/config/datasources.yml`)

```yaml
데이터 소스:
  1. Prometheus (기본)
     - URL: http://prometheus:9090
     - 용도: 메트릭 쿼리

  2. Loki
     - URL: http://loki:3100
     - 용도: 로그 쿼리

  3. Jaeger
     - URL: http://jaeger:16686
     - 용도: 분산 추적

  4. PostgreSQL
     - URL: postgres:5432
     - 용도: 직접 데이터 쿼리

  5. Redis
     - URL: redis:6379
     - 용도: 캐시 메트릭
```

---

## 테스팅 전략

### 1. 테스트 구성 (`/pytest.ini`)

```ini
테스트 디렉토리: tests/
비동기 모드: auto
Python 경로: neos

마커:
  - unit: 단위 테스트
  - integration: 통합 테스트
  - slow: 느린 테스트

커버리지:
  - 소스: neos/
  - 타겟: 70-85%
  - 리포트: term-missing, html
```

### 2. 테스트 파일 구조

```
tests/
├── test_agents.py             # 에이전트 테스트
├── test_analytics.py          # 분석 테스트
├── test_api.py               # API 테스트
├── test_auth.py              # 인증/인가 테스트
├── test_cli.py               # CLI 테스트
├── test_database.py          # 데이터베이스 테스트
├── test_document_features.py # 문서 기능 테스트
├── test_documents.py         # 문서 관리 테스트
├── test_search.py            # 검색 테스트
├── test_vision.py            # 비전 통합 테스트
├── test_web_lookup.py        # 웹 조회 테스트
├── test_web_search.py        # 웹 검색 테스트
├── test_workflow.py          # 워크플로우 테스트
├── test_workflow_builder.py  # 워크플로우 빌더 테스트
└── test_workflow_chat.py     # 워크플로우 채팅 테스트
```

**총 테스트 케이스**: 150+ 개

### 3. 테스트 레벨

#### 단위 테스트 (Unit Tests)
```python
목적: 개별 함수/클래스 테스트
격리: Mock/Stub 사용
속도: 빠름 (< 1초)
커버리지: 70%+
```

#### 통합 테스트 (Integration Tests)
```python
목적: 컴포넌트 간 상호작용 테스트
환경: 실제 DB/Redis
속도: 중간 (1-10초)
커버리지: 60%+
```

#### E2E 테스트 (End-to-End Tests)
```python
목적: 전체 워크플로우 테스트
환경: Docker Compose
속도: 느림 (10초+)
커버리지: 주요 시나리오
```

### 4. 커버리지 목표

| 모듈 | 목표 | 현재 |
|-----|------|------|
| API | 85% | 75% |
| Agents | 80% | 70% |
| Workflow | 85% | 75% |
| Database | 80% | 72% |
| Auth | 90% | 85% |
| **전체** | **85%** | **~70%** |

### 5. 테스트 실행

```bash
# 전체 테스트
pytest

# 단위 테스트만
pytest -m unit

# 통합 테스트만
pytest -m integration

# 커버리지 포함
pytest --cov=neos --cov-report=html

# 느린 테스트 제외
pytest -m "not slow"

# 병렬 실행 (4 프로세스)
pytest -n 4
```

---

## 모니터링 및 관찰성

### 1. 메트릭 수집 (Prometheus)

#### 애플리케이션 메트릭

```python
# 요청 메트릭
http_requests_total               # 총 요청 수
http_request_duration_seconds     # 요청 처리 시간
http_requests_in_progress         # 진행 중인 요청

# 워크플로우 메트릭
workflow_executions_total         # 워크플로우 실행 수
workflow_execution_duration       # 워크플로우 실행 시간
workflow_failures_total           # 워크플로우 실패 수
workflow_quality_score            # 워크플로우 품질 점수

# 에이전트 메트릭
agent_executions_total            # 에이전트 실행 수
agent_execution_errors            # 에이전트 에러 수
agent_execution_duration          # 에이전트 실행 시간

# LLM 메트릭
llm_api_calls_total               # LLM API 호출 수
llm_api_errors_total              # LLM API 에러 수
llm_cost_usd                      # LLM 비용 (USD)
llm_tokens_used                   # 사용된 토큰 수
```

#### 시스템 메트릭

```python
# CPU
process_cpu_seconds_total         # CPU 사용 시간
system_cpu_usage                  # 시스템 CPU 사용률

# 메모리
process_resident_memory_bytes     # 사용 중인 메모리
system_memory_usage               # 시스템 메모리 사용률

# 데이터베이스
pg_stat_database_*                # 데이터베이스 통계
pg_stat_user_tables_*             # 테이블 통계
pg_locks_*                        # 잠금 정보

# 캐시
redis_connected_clients           # 연결된 클라이언트
redis_memory_used_bytes           # 메모리 사용량
redis_keyspace_hits_total         # 캐시 히트
redis_keyspace_misses_total       # 캐시 미스
```

### 2. 로그 수집 (Loki)

#### 로그 레벨

```
DEBUG   - 디버깅 정보
INFO    - 일반 정보
WARNING - 경고
ERROR   - 에러
CRITICAL - 치명적 에러
```

#### 로그 소스

```yaml
Backend 로그:
  - API 요청/응답
  - 워크플로우 실행
  - 에이전트 활동
  - 에러 및 예외

Nginx 로그:
  - 액세스 로그 (combined 포맷)
  - 에러 로그

PostgreSQL 로그:
  - 쿼리 로그 (느린 쿼리)
  - 연결 로그
  - 에러 로그
```

#### 로그 쿼리 예시

```logql
# 에러 로그 검색
{job="backend"} |= "ERROR"

# 특정 워크플로우 로그
{job="backend"} | json | workflow_id="abc123"

# 느린 API 요청
{job="nginx"} | json | duration > 2s

# 5분간 에러 카운트
count_over_time({job="backend"} |= "ERROR"[5m])
```

### 3. 분산 추적 (Jaeger)

#### 추적 범위

```python
# HTTP 요청
span: http_request
  - method, path, status_code
  - request_id, user_id

# 워크플로우 실행
span: workflow_execution
  - workflow_id, workflow_name
  - steps, agents

# LLM 호출
span: llm_api_call
  - model, provider
  - tokens, cost

# 데이터베이스 쿼리
span: database_query
  - query, duration
  - rows_affected
```

#### 추적 컨텍스트

```python
# 요청 플로우
HTTP Request
  └─ Workflow Execution
      ├─ Agent 1 Execution
      │   ├─ LLM API Call
      │   └─ Database Query
      ├─ Agent 2 Execution
      │   └─ LLM API Call
      └─ Database Query
```

### 4. 대시보드

#### Grafana 대시보드

**시스템 개요**:
- 전체 요청 수 / 에러율
- 응답 시간 (P50, P95, P99)
- 활성 사용자 / 세션
- CPU / 메모리 사용률

**API 성능**:
- 엔드포인트별 요청 수
- 엔드포인트별 응답 시간
- 상태 코드 분포
- Rate Limit 히트

**워크플로우**:
- 워크플로우 실행 수
- 성공 / 실패율
- 평균 실행 시간
- 품질 점수 추이

**데이터베이스**:
- 연결 풀 사용률
- 쿼리 성능 (P95)
- 테이블 크기
- 인덱스 효율성

**캐시**:
- 히트율
- 메모리 사용량
- 키 개수
- 명령어 통계

**LLM**:
- API 호출 수
- 토큰 사용량
- 비용 추이
- 에러율

---

## 배포 프로세스

### 1. 배포 전략

#### Blue-Green Deployment

```yaml
개념: 두 개의 동일한 환경 운영 (Blue, Green)
절차:
  1. Green 환경에 새 버전 배포
  2. 헬스 체크 및 스모크 테스트
  3. 트래픽을 Green으로 전환
  4. Blue 환경 모니터링 (롤백 대비)
  5. Blue 환경 업데이트 또는 제거

장점: 무중단 배포, 빠른 롤백
단점: 2배 리소스 필요
```

#### Rolling Update

```yaml
개념: 점진적으로 인스턴스 업데이트
절차:
  1. 인스턴스 1 업데이트
  2. 헬스 체크
  3. 다음 인스턴스로 진행
  4. 모든 인스턴스 업데이트 완료

장점: 리소스 효율적
단점: 롤백 시간 길어짐
```

### 2. 배포 환경

#### Staging 환경

```yaml
트리거: main 브랜치 푸시
목적: 프로덕션 배포 전 최종 검증
스케일: 단일 인스턴스
데이터: 테스트 데이터
모니터링: 기본
```

#### Production 환경

```yaml
트리거: v* 태그 푸시
목적: 실제 서비스 제공
스케일: 3개 인스턴스 (로드 밸런싱)
데이터: 실제 데이터
모니터링: 전체 (Prometheus, Grafana, Jaeger, Loki)
백업: 자동 백업 (매일)
```

### 3. 배포 체크리스트

#### 배포 전

- [ ] 모든 CI 테스트 통과
- [ ] 코드 리뷰 승인
- [ ] 데이터베이스 마이그레이션 검증
- [ ] 변경 사항 문서화
- [ ] 롤백 계획 수립

#### 배포 중

- [ ] 헬스 체크 모니터링
- [ ] 에러율 모니터링
- [ ] 응답 시간 모니터링
- [ ] 로그 확인

#### 배포 후

- [ ] 스모크 테스트 실행
- [ ] 주요 기능 검증
- [ ] 메트릭 확인 (30분)
- [ ] 사용자 피드백 모니터링
- [ ] 배포 리포트 작성

### 4. 롤백 절차

```bash
# 1. 이전 버전 확인
docker images | grep neos

# 2. 이전 버전으로 롤백
docker-compose up -d --scale backend=3 \
  --image neos-backend:previous-tag

# 3. 헬스 체크
curl http://localhost:8518/health

# 4. 메트릭 확인
# Grafana 대시보드에서 확인

# 5. 알림 전송
# Slack 알림
```

### 5. 데이터베이스 마이그레이션

#### Alembic 사용

```bash
# 마이그레이션 생성
alembic revision --autogenerate -m "description"

# 마이그레이션 적용
alembic upgrade head

# 마이그레이션 롤백
alembic downgrade -1

# 현재 버전 확인
alembic current

# 마이그레이션 히스토리
alembic history
```

#### 마이그레이션 전략

```yaml
Zero-Downtime Migration:
  1. 새 컬럼 추가 (NULL 허용)
  2. 애플리케이션 배포 (새 컬럼 사용)
  3. 데이터 마이그레이션
  4. 기존 컬럼 제거 (다음 배포)

Breaking Change:
  1. 점검 시간 공지
  2. 서비스 일시 중단
  3. 마이그레이션 실행
  4. 애플리케이션 배포
  5. 서비스 재개
```

### 6. 백업 및 복구

#### 자동 백업 (`/scripts/backup/`)

```bash
# 전체 백업
./scripts/backup/backup-all.sh

# PostgreSQL 백업
./scripts/backup/backup-postgres.sh

# Redis 백업
./scripts/backup/backup-redis.sh

# 복구
./scripts/backup/restore-postgres.sh <backup-file>
```

#### 백업 전략

```yaml
빈도:
  - Full Backup: 매일 01:00
  - Incremental: 6시간마다
  - Redis Snapshot: 1시간마다

보존:
  - Daily: 7일
  - Weekly: 4주
  - Monthly: 12개월

저장 위치:
  - 로컬: /backups/
  - 원격: S3 / GCS (권장)

암호화: AES-256
압축: gzip
```

---

## 현재 상태 및 권장사항

### 1. 프로덕션 준비도

**전체 평가**: ⭐⭐⭐⭐☆ (85%)

#### ✅ 완료된 항목

1. **CI/CD 파이프라인**
   - GitHub Actions 워크플로우 완성
   - 자동화된 테스팅
   - 보안 스캐닝
   - 코드 품질 검증

2. **컨테이너화**
   - Docker 이미지 빌드
   - 멀티 플랫폼 지원
   - Docker Compose 구성

3. **모니터링 스택**
   - Prometheus 메트릭 수집
   - Grafana 대시보드
   - Loki 로그 수집
   - Jaeger 분산 추적
   - 17개 알림 규칙

4. **로드 밸런싱**
   - Nginx 설정
   - 3개 백엔드 복제본
   - Rate Limiting
   - 헬스 체크

5. **테스팅**
   - 150+ 테스트 케이스
   - ~70% 커버리지
   - 단위/통합/E2E 테스트

### 2. 미완료 항목

#### 🔴 Critical (P0) - 프로덕션 배포 전 필수

1. **SSL/TLS 암호화**
   - 현재: HTTP만 지원
   - 필요: HTTPS 설정 (Let's Encrypt)
   - 예상 작업: 2-3일

2. **자동 백업 구현**
   - 현재: 스크립트만 존재
   - 필요: Cron 작업 설정
   - 예상 작업: 1-2일

3. **부하 테스트**
   - 현재: 미실행
   - 필요: Locust/K6 부하 테스트
   - 예상 작업: 3-5일

4. **시크릿 관리**
   - 현재: 환경 변수
   - 필요: Vault/AWS Secrets Manager
   - 예상 작업: 3-5일

5. **실제 배포 검증**
   - 현재: 플레이스홀더 명령어
   - 필요: 실제 서버 배포 테스트
   - 예상 작업: 5-7일

#### 🟡 High Priority (P1) - 1-2개월 내 완료

1. **Redis Sentinel (HA)**
   - 현재: 단일 인스턴스
   - 필요: 3노드 Sentinel
   - 예상 작업: 3-5일

2. **테스트 커버리지 향상**
   - 현재: ~70%
   - 목표: 85%+
   - 예상 작업: 2-3주

3. **Alertmanager 통합**
   - 현재: 알림 규칙만 존재
   - 필요: 실제 알림 전송
   - 예상 작업: 2-3일

4. **보안 감사**
   - 현재: 자동 스캔만
   - 필요: 전문가 감사
   - 예상 작업: 1-2주

5. **Kubernetes 준비**
   - 현재: Docker Compose
   - 필요: K8s 매니페스트
   - 예상 작업: 2-3주

#### 🟢 Medium Priority (P2) - 3-6개월 내 완료

1. **다중 리전 배포**
   - 현재: 단일 리전
   - 필요: Multi-region
   - 예상 작업: 1-2개월

2. **고급 APM**
   - 현재: Jaeger 기본
   - 필요: Datadog/New Relic
   - 예상 작업: 1-2주

3. **자동 스케일링**
   - 현재: 수동 스케일링
   - 필요: HPA (Horizontal Pod Autoscaler)
   - 예상 작업: 1-2주

4. **Disaster Recovery 계획**
   - 현재: 백업만
   - 필요: DR 절차 문서화
   - 예상 작업: 1-2주

### 3. 권장 배포 일정

#### Phase 1: Critical Items (2-3주)

```
Week 1:
  - SSL/TLS 설정
  - 자동 백업 구현
  - 시크릿 관리 설정

Week 2:
  - 부하 테스트 실행
  - 성능 최적화
  - 실제 배포 테스트

Week 3:
  - 최종 검증
  - 문서 업데이트
  - 팀 교육
```

#### Phase 2: High Priority Items (1-2개월)

```
Month 1:
  - Redis Sentinel 설정
  - 테스트 커버리지 85% 달성
  - Alertmanager 통합
  - 보안 감사 1차

Month 2:
  - Kubernetes 매니페스트 작성
  - K8s 클러스터 설정
  - 마이그레이션 테스트
```

#### Phase 3: Medium Priority Items (3-6개월)

```
Month 3-4:
  - 다중 리전 아키텍처 설계
  - 리전별 배포
  - 글로벌 로드 밸런서

Month 5-6:
  - 고급 APM 통합
  - DR 계획 수립
  - 자동 스케일링 구현
```

### 4. 현재 사용 가능한 규모

#### ✅ 지원 가능

```yaml
사용자: < 1,000명
동시 접속: < 100명
QPS: < 50 req/s
워크플로우: < 1,000 실행/일
데이터: < 100GB
```

#### ⚠️ 추가 작업 필요

```yaml
사용자: > 10,000명
동시 접속: > 1,000명
QPS: > 500 req/s
워크플로우: > 10,000 실행/일
데이터: > 1TB
```

### 5. 비용 예상

#### 인프라 비용 (월간)

```yaml
Staging 환경:
  - Compute: $100-200
  - Database: $50-100
  - Monitoring: $50
  - Total: $200-350/월

Production 환경 (Small):
  - Compute: $300-500
  - Database: $200-300
  - Cache: $50-100
  - Load Balancer: $20-50
  - Monitoring: $100-200
  - Storage: $50-100
  - Total: $720-1,250/월

Production 환경 (Medium):
  - Compute: $800-1,200
  - Database: $500-800
  - Cache: $150-250
  - Load Balancer: $50-100
  - Monitoring: $300-500
  - Storage: $150-300
  - Total: $1,950-3,150/월
```

#### 운영 비용

```yaml
LLM API (OpenAI):
  - Light: $100-500/월
  - Medium: $500-2,000/월
  - Heavy: $2,000-10,000/월

인력:
  - DevOps Engineer: 0.5 FTE
  - Backend Engineer: 1 FTE
  - QA Engineer: 0.5 FTE
```

---

## 부록

### A. 유용한 명령어

#### Docker

```bash
# 전체 스택 시작
docker-compose -f docker-compose.enterprise.yml up -d

# 로그 확인
docker-compose logs -f backend

# 특정 서비스 재시작
docker-compose restart backend

# 스케일링
docker-compose up -d --scale backend=5

# 정리
docker-compose down -v
```

#### 테스팅

```bash
# 전체 테스트
pytest

# 커버리지 포함
pytest --cov=neos --cov-report=html

# 특정 테스트
pytest tests/test_api.py -v

# 병렬 실행
pytest -n auto
```

#### 모니터링

```bash
# Prometheus 쿼리
curl 'http://localhost:9090/api/v1/query?query=http_requests_total'

# Loki 로그
curl -G -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="backend"}' | jq

# Grafana API
curl -H "Authorization: Bearer <token>" \
  http://localhost:3000/api/dashboards/home
```

#### 데이터베이스

```bash
# psql 접속
docker-compose exec postgres psql -U neos

# 백업
pg_dump -U neos neos > backup.sql

# 복구
psql -U neos neos < backup.sql

# 마이그레이션
alembic upgrade head
```

### B. 트러블슈팅

#### 일반적인 문제

**1. 컨테이너가 시작되지 않음**
```bash
# 로그 확인
docker-compose logs backend

# 헬스 체크
docker-compose ps

# 재시작
docker-compose restart backend
```

**2. 데이터베이스 연결 실패**
```bash
# PostgreSQL 상태 확인
docker-compose exec postgres pg_isready

# 연결 테스트
psql -h localhost -U neos -d neos

# 연결 풀 확인 (Prometheus)
pg_stat_database_numbackends
```

**3. 높은 메모리 사용**
```bash
# 컨테이너 리소스 확인
docker stats

# 메모리 프로파일링
py-spy top --pid <pid>

# 캐시 정리
redis-cli FLUSHDB
```

**4. 느린 API 응답**
```bash
# Jaeger에서 추적 확인
# http://localhost:16686

# 느린 쿼리 확인
SELECT * FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;

# 인덱스 확인
SELECT * FROM pg_indexes WHERE tablename = 'your_table';
```

### C. 참고 문서

#### 내부 문서

- [Enterprise Deployment Guide](../ENTERPRISE_DEPLOYMENT.md)
- [Enterprise Readiness Checklist](../ENTERPRISE_READINESS_CHECKLIST.md)
- [Testing Guide](../TESTING_GUIDE.md)
- [Architecture](./NEOS_ARCHITECTURE.md)
- [API Documentation](./API_QUICK_START.md)

#### 외부 문서

- [Docker Documentation](https://docs.docker.com/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Nginx Documentation](https://nginx.org/en/docs/)

---

## 문서 이력

| 버전 | 날짜 | 작성자 | 변경 사항 |
|------|------|--------|-----------|
| 1.0 | 2025-11-18 | Claude | 초기 문서 작성 |

## 라이선스

이 문서는 NEOS 프로젝트의 일부이며 동일한 라이선스를 따릅니다.

---

**문의**: NEOS 개발팀
**업데이트**: 정기적으로 업데이트 예정
