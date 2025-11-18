# 인증 시스템 구현 가이드

## 개요

NEOS 프로젝트에 BFF (Backend-for-Frontend) 패턴 기반의 이중 인증 시스템이 구현되었습니다.

- **웹 로그인**: HTTP-only 쿠키 기반 세션 인증
- **API 키**: 직접 API 호출을 위한 API 키 인증

## 아키텍처

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │ HTTP-only Cookies
       ▼
┌──────────────────┐
│  Next.js BFF     │
│  (Port 3000)     │
│  - Session Store │
│  - Auth Routes   │
└──────┬───────────┘
       │ JWT Tokens
       ▼
┌──────────────────┐
│  FastAPI Backend │
│  (Port 8518)     │
│  - JWT Verify    │
│  - API Key Check │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  PostgreSQL +    │
│  Redis           │
└──────────────────┘
```

## 주요 구성 요소

### 1. Backend (FastAPI)

#### 데이터베이스 모델
- **User**: 사용자 정보 (이메일, 비밀번호 해시, 역할 등)
- **APIKey**: API 키 정보 (해시, 권한, 사용 통계 등)
- **RefreshToken**: JWT Refresh Token (토큰 rotation 지원)

위치: `neos/database/models.py`

#### 인증 서비스
- `AuthService`: 회원가입, 로그인, 토큰 관리, API 키 관리
- 위치: `neos/api/services/auth_service.py`

#### 인증 Dependencies
- `get_current_user`: JWT 또는 API 키로 현재 사용자 가져오기
- `get_current_active_user`: 활성화된 사용자만 허용
- `get_current_admin_user`: 관리자만 허용
- `require_api_key`: API 키 전용 인증

위치: `neos/api/dependencies/auth.py`

#### API 엔드포인트
- `POST /api/v1/auth/register`: 회원가입
- `POST /api/v1/auth/login`: 로그인
- `POST /api/v1/auth/refresh`: 토큰 갱신
- `POST /api/v1/auth/logout`: 로그아웃
- `GET /api/v1/auth/me`: 현재 사용자 정보
- `POST /api/v1/auth/api-keys`: API 키 생성
- `GET /api/v1/auth/api-keys`: API 키 목록
- `DELETE /api/v1/auth/api-keys/{id}`: API 키 삭제

위치: `neos/api/handlers/auth.py`

### 2. BFF Layer (Next.js)

#### Session 관리 (Redis)
- Redis를 사용한 서버 사이드 세션 관리
- 위치: `web/lib/redis.ts`

#### Auth API Routes
- `POST /api/auth/login`: 로그인 (쿠키 설정)
- `POST /api/auth/register`: 회원가입
- `POST /api/auth/logout`: 로그아웃 (쿠키 삭제)
- `GET /api/auth/me`: 현재 사용자 정보

위치: `web/app/api/auth/*/route.ts`

#### Middleware
- 보호된 경로 접근 제어
- 세션 쿠키 확인
- 위치: `web/middleware.ts`

### 3. Frontend (React)

#### Auth Context
- 전역 인증 상태 관리
- `useAuth` 훅 제공
- 위치: `web/lib/contexts/auth-context.tsx`

#### Auth Utilities
- 로그인, 로그아웃, 회원가입 함수
- 위치: `web/lib/auth.ts`

## 사용 방법

### 1. 환경 변수 설정

#### Backend (.env)
```bash
# JWT 설정
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this-in-production-min-32-chars
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Redis 설정
REDIS_URL=redis://localhost:6379

# CORS 설정
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

#### Frontend (.env.local)
```bash
BACKEND_URL=http://localhost:8518
REDIS_URL=redis://localhost:6379
```

### 2. 데이터베이스 마이그레이션

```bash
# PostgreSQL에서 마이그레이션 실행
cd neos
psql -U your_user -d your_database -f neos/database/migrations/001_add_auth_tables.sql
```

또는 Python 스크립트로 실행:

```python
from neos.database.connection import get_db

async def run_migration():
    async with get_db() as db:
        with open('neos/database/migrations/001_add_auth_tables.sql') as f:
            await db.execute(f.read())
        await db.commit()
```

### 3. 패키지 설치

#### Backend
```bash
cd neos
pip install -r requirements.txt
# 또는
pip install passlib[bcrypt] python-jose[cryptography] pyjwt alembic
```

#### Frontend
```bash
cd web
npm install
# 또는
npm install ioredis iron-session
```

### 4. 서비스 시작

```bash
# Redis 시작
redis-server

# Backend 시작
cd neos
python -m neos.main

# Frontend 시작
cd web
npm run dev
```

## 사용 예시

### 웹 애플리케이션에서 사용

```typescript
import { useAuth } from '@/lib/contexts/auth-context';

function LoginPage() {
  const { login } = useAuth();

  const handleLogin = async () => {
    try {
      await login('user@example.com', 'password123');
      // 로그인 성공 시 자동으로 쿠키가 설정됨
      router.push('/dashboard');
    } catch (error) {
      console.error('Login failed:', error);
    }
  };

  return <button onClick={handleLogin}>로그인</button>;
}
```

### API 키로 직접 백엔드 호출

```python
import requests

# 1. 로그인하여 API 키 생성
response = requests.post(
    'http://localhost:8518/api/v1/auth/login',
    json={'email': 'user@example.com', 'password': 'password123'}
)
access_token = response.json()['access_token']

# 2. API 키 생성
response = requests.post(
    'http://localhost:8518/api/v1/auth/api-keys',
    headers={'Authorization': f'Bearer {access_token}'},
    json={
        'name': 'My API Key',
        'scopes': ['query:read', 'chat:write'],
        'rate_limit': 100
    }
)
api_key = response.json()['data']['key']  # 1회만 표시됨!

# 3. API 키로 API 호출
response = requests.post(
    'http://localhost:8518/api/v1/query',
    headers={'X-API-Key': api_key},
    json={'query': 'What is AI?', 'user_id': 'user_123'}
)
```

### 보호된 엔드포인트 만들기

```python
from fastapi import APIRouter, Depends
from neos.api.dependencies.auth import get_current_active_user
from neos.database.models import User

router = APIRouter()

@router.get("/protected")
async def protected_route(
    current_user: User = Depends(get_current_active_user)
):
    return {
        "message": "This is a protected route",
        "user": current_user.email
    }
```

## 보안 권장사항

### 1. JWT Secret 키
- 최소 32자 이상의 강력한 랜덤 문자열 사용
- 절대 버전 관리 시스템에 커밋하지 말 것
- 프로덕션 환경에서는 환경 변수로 관리

```bash
# 강력한 시크릿 키 생성
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. 비밀번호 정책
- 최소 8자 이상
- 대문자, 소문자, 숫자, 특수문자 포함
- 설정 위치: `neos/config/settings.py`

### 3. HTTPS 사용
- 프로덕션 환경에서는 반드시 HTTPS 사용
- HTTP-only 쿠키는 HTTPS에서만 안전

### 4. CORS 설정
- 프로덕션 환경에서는 허용된 도메인만 명시
- 와일드카드(`*`) 사용 금지

### 5. Rate Limiting
- API 키별 요청 제한 설정
- 로그인 시도 제한 (5회/10분)

## 트러블슈팅

### Redis 연결 오류
```bash
# Redis가 실행 중인지 확인
redis-cli ping
# 응답: PONG

# Redis 로그 확인
tail -f /var/log/redis/redis-server.log
```

### 세션이 유지되지 않음
- 쿠키 설정 확인 (HttpOnly, Secure, SameSite)
- CORS 설정 확인 (`credentials: true`)
- Redis 연결 확인

### JWT 토큰 검증 실패
- JWT_SECRET_KEY가 일치하는지 확인
- 토큰 만료 시간 확인
- 시스템 시간이 동기화되어 있는지 확인

## 추가 기능 (향후 계획)

- [ ] 이메일 인증
- [ ] 비밀번호 재설정
- [ ] 2FA (Two-Factor Authentication)
- [ ] OAuth 연동 (Google, GitHub 등)
- [ ] RBAC (Role-Based Access Control) 강화
- [ ] 감사 로그 (Audit Log)
- [ ] Rate Limiting (고급)
- [ ] CSRF 토큰 검증

## 참고 자료

- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [JWT.io](https://jwt.io/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [Next.js Authentication](https://nextjs.org/docs/authentication)
