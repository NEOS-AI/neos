# API 키 Scope 검증 및 Rate Limiting 사용 가이드

## 📋 개요

이 문서는 NEOS 백엔드에 새롭게 추가된 두 가지 보안 기능의 사용법을 설명합니다:
1. **API 키 Scope 검증**: 세분화된 권한 제어
2. **Redis 기반 Rate Limiting**: 요청 제한 및 DoS 방어

---

## 🔐 1. API 키 Scope 검증

### 개념

Scope는 API 키가 수행할 수 있는 작업을 정의하는 권한 문자열입니다.

**형식**: `{resource}:{action}`

**예시**:
- `query:read` - 쿼리 조회 권한
- `query:write` - 쿼리 생성 권한
- `document:upload` - 문서 업로드 권한
- `chat:write` - 채팅 메시지 전송 권한
- `analytics:read` - 분석 데이터 조회 권한

### 사용법 1: 클래스 기반 (권장)

```python
from fastapi import APIRouter, Depends
from neos.api.dependencies.auth import require_scopes

router = APIRouter()

@router.get(
    "/documents",
    dependencies=[Depends(require_scopes(["document:read"]))]
)
async def list_documents():
    """문서 목록 조회 (document:read 권한 필요)"""
    return {"documents": [...]}

@router.post(
    "/documents",
    dependencies=[Depends(require_scopes(["document:write"]))]
)
async def upload_document():
    """문서 업로드 (document:write 권한 필요)"""
    return {"status": "uploaded"}

@router.post(
    "/analytics/export",
    dependencies=[Depends(require_scopes(["analytics:read", "export:write"]))]
)
async def export_analytics():
    """분석 데이터 내보내기 (2개 권한 필요)"""
    return {"status": "exporting"}
```

### 사용법 2: 수동 검증

```python
from fastapi import Depends
from neos.api.dependencies.auth import get_current_user_from_api_key

@router.post("/advanced-operation")
async def advanced_operation(
    api_key_result: tuple = Depends(get_current_user_from_api_key)
):
    if not api_key_result:
        raise HTTPException(401, "API key required")

    api_key_obj, user = api_key_result

    # 수동 scope 검증
    required_scopes = ["operation:execute", "data:write"]
    api_key_scopes = set(api_key_obj.scopes or [])

    if not set(required_scopes).issubset(api_key_scopes):
        raise HTTPException(403, "Insufficient permissions")

    # 작업 수행
    return {"status": "ok"}
```

### JWT vs API 키 권한

| 인증 방식 | Scope 제한 | 이유 |
|----------|-----------|------|
| **JWT** | ❌ 제한 없음 | 사용자가 직접 로그인 (모든 권한) |
| **API 키** | ✅ Scope 검증 | 3rd party 통합용 (제한된 권한) |

### API 키 생성 시 Scope 설정

```bash
curl -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Document Processor",
    "description": "문서 처리 서비스용",
    "scopes": ["document:read", "document:write", "document:delete"],
    "rate_limit": 100,
    "max_requests_per_day": 10000
  }'
```

### Scope 검증 실패 응답

```json
{
  "detail": {
    "error": "insufficient_permissions",
    "message": "API 키에 필요한 권한이 없습니다.",
    "required_scopes": ["document:write", "analytics:read"],
    "missing_scopes": ["analytics:read"]
  }
}
```

**HTTP 상태 코드**: `403 Forbidden`

---

## 🚦 2. Redis 기반 Rate Limiting

### 특징

- **알고리즘**: Sliding Window (정확한 요청 수 카운팅)
- **저장소**: Redis (분산 환경 지원)
- **Fail-open**: Redis 장애 시 요청 허용 (가용성 우선)
- **메타데이터**: 헤더를 통한 제한 정보 제공

### 사용법 1: API 키 자동 Rate Limiting

`require_api_key`를 사용하면 자동으로 rate limiting이 적용됩니다.

```python
from fastapi import Depends
from neos.api.dependencies.auth import require_api_key

@router.post("/data")
async def create_data(
    auth: tuple = Depends(require_api_key)
):
    api_key_obj, user = auth
    # API 키의 rate_limit, max_requests_per_day 설정에 따라 자동 제한
    return {"status": "created"}
```

**제한 규칙**:
- **분당 제한**: `api_key_obj.rate_limit` (예: 100req/min)
- **일일 제한**: `api_key_obj.max_requests_per_day` (예: 10,000req/day)

### 사용법 2: IP 기반 Rate Limiting

```python
from fastapi import Depends
from neos.api.dependencies.auth import check_ip_rate_limit

@router.get(
    "/public/data",
    dependencies=[Depends(check_ip_rate_limit)]
)
async def get_public_data():
    """IP별 60req/min 제한"""
    return {"data": "..."}
```

### 사용법 3: 커스텀 Rate Limiting

```python
from fastapi import Depends
from neos.api.dependencies.auth import RateLimitChecker

# 100 requests per 60 seconds
@router.post(
    "/heavy-operation",
    dependencies=[Depends(RateLimitChecker(100, 60))]
)
async def heavy_operation():
    """100req/min 제한"""
    return {"status": "processing"}

# 10 requests per 3600 seconds (1 hour)
@router.post(
    "/expensive-operation",
    dependencies=[Depends(RateLimitChecker(10, 3600))]
)
async def expensive_operation():
    """10req/hour 제한"""
    return {"status": "processing"}
```

### Rate Limit 응답 헤더

```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1704067200
Retry-After: 45

{
  "detail": {
    "error": "rate_limit_exceeded",
    "message": "API 키 요청 제한을 초과했습니다.",
    "limit": 100,
    "current": 101,
    "retry_after": 45
  }
}
```

**헤더 설명**:
- `X-RateLimit-Limit`: 최대 요청 수
- `X-RateLimit-Remaining`: 남은 요청 수
- `X-RateLimit-Reset`: 리셋 시간 (UNIX timestamp)
- `Retry-After`: 재시도까지 대기 시간 (초)

### Redis 연결 설정

```bash
# .env 파일
REDIS_URL=redis://localhost:6379
REDIS_POOL_SIZE=50
REDIS_MIN_IDLE_CONNECTIONS=10
```

### FastAPI 앱 시작/종료 시 Redis 초기화

```python
from fastapi import FastAPI
from neos.utils.rate_limiter import rate_limiter

app = FastAPI()

@app.on_event("startup")
async def startup():
    """앱 시작 시 Redis 초기화"""
    await rate_limiter.initialize()
    print("✅ Rate limiter initialized")

@app.on_event("shutdown")
async def shutdown():
    """앱 종료 시 Redis 연결 종료"""
    await rate_limiter.close()
    print("✅ Rate limiter connection closed")
```

---

## 🎯 실전 예시: 조합 사용

### 예시 1: 문서 업로드 API

```python
from fastapi import APIRouter, Depends, UploadFile
from neos.api.dependencies.auth import require_scopes, RateLimitChecker

router = APIRouter()

@router.post(
    "/documents/upload",
    dependencies=[
        Depends(require_scopes(["document:write"])),  # Scope 검증
        Depends(RateLimitChecker(10, 60))  # 10 uploads/min
    ]
)
async def upload_document(file: UploadFile):
    """
    문서 업로드
    - 권한: document:write
    - 제한: 10 uploads/min
    """
    return {"filename": file.filename, "status": "uploaded"}
```

### 예시 2: 분석 데이터 조회 API

```python
@router.get(
    "/analytics/dashboard",
    dependencies=[Depends(require_scopes(["analytics:read"]))]
)
async def get_dashboard(
    auth: tuple = Depends(require_api_key)
):
    """
    대시보드 데이터 조회
    - 권한: analytics:read
    - 제한: API 키 기본 설정 (예: 100req/min)
    """
    api_key_obj, user = auth

    # request.state.rate_limit_metadata에서 메타데이터 확인 가능
    return {"data": {...}}
```

### 예시 3: 공개 API (IP 제한만)

```python
@router.get(
    "/public/status",
    dependencies=[Depends(check_ip_rate_limit)]
)
async def get_status():
    """
    시스템 상태 조회
    - 인증: 불필요
    - 제한: IP별 60req/min
    """
    return {"status": "healthy"}
```

---

## 🧪 테스트

### Scope 검증 테스트

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_scope_verification():
    # API 키 생성 (scopes: ["document:read"])
    response = await client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={
            "name": "Test Key",
            "scopes": ["document:read"]
        }
    )
    api_key = response.json()["data"]["key"]

    # document:read 권한 있음 → 성공
    response = await client.get(
        "/api/v1/documents",
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200

    # document:write 권한 없음 → 실패
    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": api_key},
        json={"title": "Test"}
    )
    assert response.status_code == 403
    assert "missing_scopes" in response.json()["detail"]
```

### Rate Limiting 테스트

```python
@pytest.mark.asyncio
async def test_rate_limiting():
    # API 키 생성 (rate_limit: 5/min)
    response = await client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={
            "name": "Rate Test Key",
            "rate_limit": 5
        }
    )
    api_key = response.json()["data"]["key"]

    # 5번 요청 성공
    for i in range(5):
        response = await client.get(
            "/api/v1/documents",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        assert int(response.headers["X-RateLimit-Remaining"]) == 4 - i

    # 6번째 요청 실패 (rate limit 초과)
    response = await client.get(
        "/api/v1/documents",
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 429
    assert "retry_after" in response.json()["detail"]
```

---

## 📊 모니터링

### 로그 확인

```bash
# Scope 검증 실패
grep "API key scope verification failed" logs/neos.log

# Rate limit 초과
grep "Rate limit exceeded" logs/neos.log

# IP rate limit 초과
grep "IP rate limit exceeded" logs/neos.log
```

### Redis 모니터링

```bash
# Redis에서 rate limit 키 확인
redis-cli KEYS "rate_limit:*"

# 특정 API 키의 요청 수 확인
redis-cli ZCARD "rate_limit:api_key:YOUR_KEY_ID:minute"

# IP별 요청 수 확인
redis-cli ZCARD "rate_limit:ip:192.168.1.1"
```

---

## ⚙️ 설정 권장사항

### API 키 Scope 분류

| 용도 | Scope 목록 | 설명 |
|------|-----------|------|
| **읽기 전용** | `["query:read", "document:read", "analytics:read"]` | 데이터 조회만 |
| **문서 관리** | `["document:read", "document:write", "document:delete"]` | 문서 CRUD |
| **채팅 봇** | `["chat:write", "query:read"]` | 채팅 + 쿼리 |
| **관리자** | `["*"]` | 모든 권한 (JWT 권장) |

### Rate Limit 설정

| 플랜 | 분당 | 일일 | 용도 |
|------|------|------|------|
| **Free** | 10 | 1,000 | 개인 테스트 |
| **Basic** | 60 | 10,000 | 소규모 앱 |
| **Pro** | 300 | 100,000 | 중대형 앱 |
| **Enterprise** | 1,000 | 무제한 | 대규모 통합 |

---

## 🚨 주의사항

### Scope 검증

1. **JWT는 scope 제한 없음**: JWT로 로그인한 사용자는 모든 작업 가능
2. **빈 scopes 배열**: `scopes=[]`인 API 키는 아무 권한도 없음
3. **대소문자 구분**: `document:Read`와 `document:read`는 다름

### Rate Limiting

1. **Redis 장애**: Redis 연결 실패 시 요청 허용 (Fail-open)
2. **분산 환경**: 여러 서버에서 Redis를 공유해야 정확한 제한
3. **테스트 환경**: Redis 없이도 작동하지만 rate limiting은 비활성화

---

## 🔜 향후 개선 계획

1. **Dynamic Scope 관리**: DB에서 scope 목록 동적 로드
2. **Rate Limit 통계 대시보드**: 사용자별/API 키별 사용량 시각화
3. **Burst Allowance**: 짧은 시간 폭증 허용
4. **IP 화이트리스트**: 특정 IP는 rate limit 면제

---

## 📚 참고 자료

- [OAuth 2.0 Scopes](https://oauth.net/2/scope/)
- [Rate Limiting Patterns](https://cloud.google.com/architecture/rate-limiting-strategies-techniques)
- [Redis Rate Limiter Pattern](https://redis.io/docs/manual/patterns/rate-limiter/)
