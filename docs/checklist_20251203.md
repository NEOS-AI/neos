# 네오스 백엔드 배포 체크리스트 (2025-12-03)

> **Phase 1-4 개선 사항 배포를 위한 체크리스트**
>
> 커밋: `9633b19` | 브랜치: `claude/analyze-neos-backend-01AXJFdc69r6Sc3zprPpNiXL`

---

## 📋 목차

1. [배포 전 필수 작업](#배포-전-필수-작업)
2. [환경 설정](#환경-설정)
3. [데이터베이스 준비](#데이터베이스-준비)
4. [API Key 마이그레이션](#api-key-마이그레이션)
5. [배포 실행](#배포-실행)
6. [배포 후 확인](#배포-후-확인)
7. [모니터링 설정](#모니터링-설정)
8. [롤백 계획](#롤백-계획)

---

## 🚨 배포 전 필수 작업

### 1. 코드 리뷰 및 테스트

- [ ] **PR 리뷰 완료**
  - GitHub PR: https://github.com/NEOS-AI/neos/pull/new/claude/analyze-neos-backend-01AXJFdc69r6Sc3zprPpNiXL
  - 최소 1명 이상의 팀원 승인 필요

- [ ] **로컬 테스트 실행**
  ```bash
  # 가상환경 활성화
  source venv/bin/activate

  # 테스트 실행
  pytest tests/ -v

  # 특히 인증 관련 테스트 확인
  pytest tests/test_auth_service.py -v
  pytest tests/test_auth_api.py -v
  ```

- [ ] **Breaking Changes 확인**
  - JWT_SECRET_KEY 필수화
  - API Key 해싱 알고리즘 변경 (SHA-256 → bcrypt)
  - DB 연결 풀 설정 변경

### 2. 백업 생성

- [ ] **데이터베이스 백업**
  ```bash
  # PostgreSQL 백업 (프로덕션)
  pg_dump -h <host> -U <user> -d neos_db > backup_20251203_pre_deploy.sql

  # 백업 파일 크기 확인
  ls -lh backup_20251203_pre_deploy.sql

  # S3 또는 안전한 위치에 업로드
  aws s3 cp backup_20251203_pre_deploy.sql s3://neos-backups/
  ```

- [ ] **Redis 백업 (선택)**
  ```bash
  # Redis RDB 백업
  redis-cli BGSAVE

  # 백업 파일 확인
  ls -lh /var/lib/redis/dump.rdb
  ```

- [ ] **환경 설정 백업**
  ```bash
  # 현재 .env 파일 백업 (민감정보 주의!)
  cp .env .env.backup.20251203

  # Git에 커밋하지 않도록 주의
  echo ".env.backup.*" >> .gitignore
  ```

### 3. 사용자 공지

- [ ] **서비스 중단 공지** (권장: 배포 24시간 전)
  - 배포 일시 및 예상 소요 시간
  - API Key 재생성 필요성 안내
  - 임시 서비스 중단 가능성

- [ ] **공지 채널**
  - [ ] 이메일 공지
  - [ ] 사용자 대시보드 알림
  - [ ] 슬랙/디스코드 공지

---

## ⚙️ 환경 설정

### 1. JWT Secret Key 생성 (필수!)

```bash
# 안전한 JWT Secret Key 생성
JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
echo "JWT_SECRET_KEY=$JWT_SECRET_KEY"

# .env 파일에 추가
echo "JWT_SECRET_KEY=$JWT_SECRET_KEY" >> .env
```

**⚠️ 중요:**
- 생성된 키를 안전한 곳에 보관 (비밀번호 관리자, Vault 등)
- 프로덕션과 스테이징 환경은 **다른 키** 사용
- 키를 Git에 커밋하지 않도록 주의

### 2. 환경 변수 설정

`.env.template`을 참고하여 `.env` 파일 업데이트:

```bash
# 필수 환경 변수 체크리스트
- [ ] JWT_SECRET_KEY (새로 생성)
- [ ] DATABASE_URL
- [ ] REDIS_URL
- [ ] OPENAI_API_KEY
- [ ] ANTHROPIC_API_KEY
- [ ] TAVILY_API_KEY

# 연결 풀 설정 (변경됨)
- [ ] DATABASE_POOL_SIZE=20
- [ ] DATABASE_MAX_OVERFLOW=30

# Semantic Cache 설정 (변경됨)
- [ ] SEMANTIC_CACHE_ENABLED=true
- [ ] SEMANTIC_CACHE_THRESHOLD=0.90

# CORS 설정 확인
- [ ] CORS_ALLOWED_ORIGINS (프로덕션 도메인으로 설정)
```

### 3. 환경 변수 검증

```bash
# 필수 변수 확인 스크립트
python << 'EOF'
import os
import sys

required_vars = [
    "JWT_SECRET_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY"
]

missing = []
for var in required_vars:
    if not os.getenv(var):
        missing.append(var)

if missing:
    print(f"❌ Missing environment variables: {', '.join(missing)}")
    sys.exit(1)
else:
    print("✅ All required environment variables are set")
EOF
```

---

## 🗄️ 데이터베이스 준비

### 1. PostgreSQL max_connections 확인

```sql
-- 현재 설정 확인
SHOW max_connections;

-- 현재 연결 수 확인
SELECT count(*) FROM pg_stat_activity;

-- max_connections가 100 미만이면 증가 필요
-- 권장: 150 이상
```

**max_connections 변경 (필요시):**

```bash
# postgresql.conf 수정
sudo nano /etc/postgresql/15/main/postgresql.conf

# 다음 줄 수정:
# max_connections = 150

# PostgreSQL 재시작
sudo systemctl restart postgresql
```

### 2. 연결 풀 모니터링 쿼리 준비

```sql
-- 활성 연결 모니터링
CREATE OR REPLACE VIEW active_connections AS
SELECT
    datname,
    usename,
    application_name,
    client_addr,
    state,
    COUNT(*) as connection_count
FROM pg_stat_activity
WHERE state IS NOT NULL
GROUP BY datname, usename, application_name, client_addr, state
ORDER BY connection_count DESC;

-- 연결 풀 상태 확인용
SELECT * FROM active_connections;
```

### 3. 데이터베이스 마이그레이션 (필요시)

```bash
# Alembic 마이그레이션 확인
alembic current
alembic history

# 마이그레이션 실행 (있는 경우)
alembic upgrade head
```

---

## 🔑 API Key 마이그레이션

### ⚠️ Breaking Change: API Key 해싱 변경

기존 SHA-256 해시된 API Key는 새로운 bcrypt 시스템과 호환되지 않습니다.

### 1. 기존 API Key 현황 파악

```sql
-- 현재 활성 API Key 수 확인
SELECT
    COUNT(*) as total_keys,
    COUNT(CASE WHEN is_active THEN 1 END) as active_keys,
    COUNT(DISTINCT user_id) as unique_users
FROM api_keys;

-- 사용자별 API Key 현황
SELECT
    u.user_id,
    u.email,
    u.username,
    COUNT(k.id) as key_count,
    MAX(k.last_used_at) as last_used
FROM users u
LEFT JOIN api_keys k ON u.user_id = k.user_id AND k.is_active = true
GROUP BY u.user_id, u.email, u.username
HAVING COUNT(k.id) > 0
ORDER BY last_used DESC;
```

### 2. API Key 마이그레이션 전략

**옵션 A: 전체 무효화 및 재생성 (권장)**

```sql
-- 모든 기존 API Key 비활성화
UPDATE api_keys
SET is_active = false,
    revoked_at = NOW()
WHERE is_active = true;

-- 사용자에게 재생성 요청 이메일 발송
```

**옵션 B: 단계적 마이그레이션 (사용자 많은 경우)**

```sql
-- 1단계: 30일 이상 미사용 키 비활성화
UPDATE api_keys
SET is_active = false,
    revoked_at = NOW()
WHERE is_active = true
  AND (last_used_at < NOW() - INTERVAL '30 days' OR last_used_at IS NULL);

-- 2단계: 활성 사용자에게 순차적으로 재생성 요청
-- (마이그레이션 스크립트 필요)
```

### 3. 사용자 공지 이메일 템플릿

```
제목: [중요] 네오스 API Key 재생성 필요

안녕하세요,

보안 강화를 위해 API Key 해싱 알고리즘을 업그레이드했습니다.
기존 API Key는 2025-12-10까지 사용 가능하며, 이후 자동으로 만료됩니다.

새로운 API Key를 생성해주세요:
1. https://neos.ai/dashboard/api-keys 접속
2. "새 API Key 생성" 클릭
3. 생성된 키를 안전한 곳에 보관

문의사항: support@neos.ai

감사합니다.
네오스 팀
```

---

## 🚀 배포 실행

### 1. 배포 전 최종 체크

```bash
# 체크리스트
- [ ] PR 머지 완료
- [ ] 데이터베이스 백업 완료
- [ ] 환경 변수 설정 완료
- [ ] JWT_SECRET_KEY 설정 확인
- [ ] 사용자 공지 완료
- [ ] 팀원들과 배포 시간 조율
```

### 2. 배포 절차

#### 스테이징 환경 배포

```bash
# 1. 스테이징 서버 접속
ssh user@staging.neos.ai

# 2. 코드 업데이트
cd /opt/neos
git fetch origin
git checkout claude/analyze-neos-backend-01AXJFdc69r6Sc3zprPpNiXL
git pull origin claude/analyze-neos-backend-01AXJFdc69r6Sc3zprPpNiXL

# 3. 의존성 업데이트
source venv/bin/activate
pip install -r requirements.txt

# 4. 환경 변수 확인
cat .env | grep JWT_SECRET_KEY

# 5. 애플리케이션 재시작
sudo systemctl restart neos-backend

# 6. 로그 확인
sudo journalctl -u neos-backend -f
```

#### 프로덕션 배포 (스테이징 검증 후)

```bash
# 1. 프로덕션 서버 접속
ssh user@prod.neos.ai

# 2. 배포 스크립트 실행
cd /opt/neos
./scripts/deploy.sh
```

**deploy.sh 스크립트 예시:**

```bash
#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# 코드 업데이트
git fetch origin
git checkout claude/analyze-neos-backend-01AXJFdc69r6Sc3zprPpNiXL
git pull origin claude/analyze-neos-backend-01AXJFdc69r6Sc3zprPpNiXL

# 의존성 업데이트
source venv/bin/activate
pip install -r requirements.txt

# 환경 변수 검증
python -c "from neos.config.settings import settings; print('✅ Settings loaded')"

# 애플리케이션 재시작
sudo systemctl restart neos-backend

# Health check
sleep 5
curl -f http://localhost:8518/api/v1/health || exit 1

echo "✅ Deployment completed successfully"
```

### 3. Blue-Green 배포 (권장)

```bash
# 1. Green 환경에 새 버전 배포
# 2. Health check 통과 확인
# 3. 로드밸런서 트래픽 전환
# 4. Blue 환경 모니터링
# 5. 문제 없으면 Blue 환경도 업데이트
```

---

## ✅ 배포 후 확인

### 1. 즉시 확인 (배포 후 5분 이내)

```bash
# Health Check
curl http://localhost:8518/api/v1/health
# 예상 응답: {"status": "healthy", "database": true, "cache": true}

# API 버전 확인
curl http://localhost:8518/ | jq '.version'
# 예상 응답: "0.12.0"

# 로그 확인 (에러 없는지)
sudo journalctl -u neos-backend --since "5 minutes ago" | grep -i error

# JWT 필수 확인 (환경 변수 미설정 시 시작 실패해야 함)
# 예상: "JWT_SECRET_KEY must be set in environment variables"
```

### 2. 기능 테스트 (배포 후 15분 이내)

#### 인증 기능

```bash
# 회원가입
curl -X POST http://localhost:8518/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestP@ssw0rd123",
    "username": "testuser"
  }'

# 로그인
curl -X POST http://localhost:8518/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestP@ssw0rd123"
  }'

# Access Token 받았는지 확인
```

#### API Key 생성

```bash
# API Key 생성 (위에서 받은 access_token 사용)
curl -X POST http://localhost:8518/api/v1/auth/api-keys \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test API Key",
    "description": "Deployment verification"
  }'

# 응답에서 "key" 필드 확인 (neos_로 시작)
```

#### Circuit Breaker 확인

```bash
# RealtimeDataSearchAgent 호출
curl -X POST http://localhost:8518/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "latest bitcoin price",
    "user_id": "test_user"
  }'

# Circuit Breaker 상태 확인 (로그)
sudo journalctl -u neos-backend | grep -i "circuit"
```

### 3. 데이터베이스 확인

```sql
-- 연결 풀 상태
SELECT * FROM active_connections WHERE application_name = 'neos_multi_agent';

-- 새로운 API Key 형식 확인 (bcrypt 해시)
SELECT
    key_prefix,
    LEFT(key_hash, 10) as hash_preview,
    LENGTH(key_hash) as hash_length,
    created_at
FROM api_keys
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 5;
-- bcrypt 해시는 60자, $2b$로 시작

-- JWT 필수 적용 후 새 사용자 생성 확인
SELECT user_id, email, created_at
FROM users
WHERE created_at > NOW() - INTERVAL '1 hour';
```

### 4. 캐시 확인

```bash
# Redis 연결 확인
redis-cli ping
# PONG

# Semantic Cache 확인
redis-cli keys "semantic:*" | head -5

# 캐시 히트율 (배포 후 1시간 뒤 확인)
redis-cli info stats | grep keyspace
```

### 5. 에러 모니터링 (배포 후 1시간)

```bash
# 에러 로그 확인
sudo journalctl -u neos-backend --since "1 hour ago" | grep -i "error\|exception" | wc -l

# 4xx 에러 (클라이언트 오류)
sudo journalctl -u neos-backend --since "1 hour ago" | grep "🟡 Client error"

# 5xx 에러 (서버 오류)
sudo journalctl -u neos-backend --since "1 hour ago" | grep "🔴 Server error"

# Circuit Breaker OPEN 이벤트
sudo journalctl -u neos-backend --since "1 hour ago" | grep "Circuit Breaker OPEN"
```

---

## 📊 모니터링 설정

### 1. Prometheus Metrics 확인

```bash
# Metrics endpoint 접근
curl http://localhost:8518/metrics

# 주요 메트릭 확인
curl http://localhost:8518/metrics | grep -E "http_requests_total|circuit_breaker"
```

### 2. Grafana 대시보드

**알림 설정:**

```yaml
# prometheus/alerts.yml
groups:
  - name: neos_alerts
    interval: 30s
    rules:
      # Circuit Breaker OPEN 알림
      - alert: CircuitBreakerOpen
        expr: circuit_breaker_state{state="open"} > 0
        for: 1m
        annotations:
          summary: "Circuit Breaker is OPEN for {{ $labels.agent_name }}"
          description: "Agent {{ $labels.agent_name }} is experiencing failures"

      # API 에러율 증가
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} errors/sec"

      # DB 연결 풀 고갈 경고
      - alert: DatabasePoolExhaustion
        expr: database_pool_checked_out / database_pool_size > 0.9
        for: 2m
        annotations:
          summary: "Database connection pool nearly exhausted"
          description: "{{ $value }}% of pool in use"
```

### 3. 로그 집계 (ELK/Loki)

```bash
# Loki로 로그 쿼리
logcli query '{job="neos-backend"} |= "error"' --since=1h

# 에러 빈도 분석
logcli query '{job="neos-backend"} |= "error"' --since=1h | grep -oP '"type":"\K[^"]+' | sort | uniq -c | sort -rn
```

### 4. 알림 채널 설정

- [ ] **Slack/Discord 웹훅 설정**
- [ ] **이메일 알림 설정**
- [ ] **PagerDuty 연동 (24/7 서비스인 경우)**
- [ ] **온콜 담당자 지정**

---

## 🔥 롤백 계획

### 롤백이 필요한 상황

- [ ] Health Check 실패
- [ ] 5분 이상 500 에러 지속
- [ ] 사용자 로그인 실패율 > 10%
- [ ] DB 연결 풀 고갈
- [ ] Circuit Breaker 다수 OPEN

### 롤백 절차

```bash
# 1. 이전 버전으로 코드 롤백
git checkout <previous_commit>

# 2. 애플리케이션 재시작
sudo systemctl restart neos-backend

# 3. Health Check
curl http://localhost:8518/api/v1/health

# 4. 데이터베이스 롤백 (필요시)
psql -h <host> -U <user> -d neos_db < backup_20251203_pre_deploy.sql

# 5. 사용자 공지
echo "서비스가 임시로 이전 버전으로 되돌아갔습니다." | notify-slack
```

### 부분 롤백 (환경 변수만)

```bash
# .env 파일 복구
cp .env.backup.20251203 .env

# 애플리케이션 재시작
sudo systemctl restart neos-backend
```

---

## 📝 배포 완료 체크리스트

### 배포 직후

- [ ] Health Check 통과
- [ ] 로그인/회원가입 정상 동작
- [ ] API Key 생성 정상 동작
- [ ] 에러 로그 없음 (또는 예상된 에러만)
- [ ] Circuit Breaker 정상 동작

### 배포 후 1시간

- [ ] 5xx 에러율 < 0.1%
- [ ] API 응답 시간 정상
- [ ] DB 연결 풀 사용률 < 80%
- [ ] Redis 캐시 히트율 > 50%
- [ ] Semantic Cache 활성화 확인

### 배포 후 24시간

- [ ] 사용자 불만 없음
- [ ] 시스템 메트릭 안정적
- [ ] API Key 재생성율 모니터링
- [ ] Circuit Breaker 이벤트 검토
- [ ] 성능 개선 확인 (Semantic Cache 효과)

### 배포 후 1주일

- [ ] API Key 마이그레이션 완료율 > 80%
- [ ] 구 API Key 만료 준비
- [ ] 사용자 피드백 수집
- [ ] 성능 벤치마크 비교
- [ ] 배포 회고 미팅

---

## 🆘 긴급 연락처

| 역할 | 이름 | 연락처 | 비고 |
|------|------|--------|------|
| Backend Lead | - | - | 24/7 온콜 |
| DevOps | - | - | 인프라 담당 |
| DB Admin | - | - | DB 이슈 |
| Security | - | - | 보안 이슈 |

---

## 📚 참고 문서

- [Phase 1-4 개선 사항 요약](../README.md)
- [API Key 마이그레이션 가이드](./API_KEY_MIGRATION.md)
- [Circuit Breaker 운영 가이드](./CIRCUIT_BREAKER.md)
- [커스텀 예외 처리 가이드](./ERROR_HANDLING.md)
- [환경 변수 설정 가이드](../.env.template)

---

## 📅 타임라인

| 일시 | 작업 | 담당자 | 상태 |
|------|------|--------|------|
| 2025-12-03 | Phase 1-4 개선 완료 | Claude | ✅ |
| 2025-12-04 | PR 리뷰 | Team | ⏳ |
| 2025-12-05 | 스테이징 배포 | DevOps | ⏳ |
| 2025-12-06 | 프로덕션 배포 | DevOps | ⏳ |
| 2025-12-07~10 | 모니터링 집중 | All | ⏳ |
| 2025-12-13 | 구 API Key 만료 | Backend | ⏳ |
| 2025-12-20 | 배포 회고 | All | ⏳ |

---

**작성일:** 2025-12-03
**버전:** 1.0
**다음 업데이트:** 배포 완료 후

---

## ✅ 서명

배포를 승인하기 전에 다음 항목을 확인하고 서명하세요:

- [ ] 모든 체크리스트 항목 완료
- [ ] 백업 완료 및 검증
- [ ] 롤백 계획 숙지
- [ ] 긴급 연락망 확인

**배포 승인자:**

- Backend Lead: _____________ 날짜: _______
- DevOps: _____________ 날짜: _______
- CTO: _____________ 날짜: _______
