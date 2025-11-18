# CSRF 보호 및 테스트 가이드

## CSRF 보호 구현

### 개요

CSRF (Cross-Site Request Forgery) 공격으로부터 보호하기 위해 토큰 기반 검증 시스템을 구현했습니다.

### 아키텍처

```
[Browser] → CSRF Token in Cookie
     ↓
[JavaScript] → Include token in X-CSRF-Token header
     ↓
[Next.js BFF] → Validate token
     ↓
[Backend API]
```

---

## CSRF 보호 구성요소

### 1. Backend (Python)

#### CSRF 유틸리티 (`neos/utils/csrf.py`)

```python
from neos.utils.csrf import (
    generate_csrf_token,
    create_csrf_token_with_signature,
    verify_csrf_token,
    verify_csrf_token_simple
)

# 단순 토큰 생성
token = generate_csrf_token()

# 서명된 토큰 생성 (세션 ID 포함)
signed_token = create_csrf_token_with_signature(session_id)

# 서명된 토큰 검증
is_valid = verify_csrf_token(signed_token, session_id, max_age_seconds=3600)
```

**특징:**
- URL-safe base64 인코딩
- HMAC SHA-256 서명
- 타임스탬프 기반 만료
- 타이밍 공격 방지 (constant-time comparison)

---

### 2. BFF Layer (Next.js)

#### CSRF 토큰 발급 (`/api/auth/csrf`)

```typescript
// CSRF 토큰 요청
GET /api/auth/csrf

// 응답
{
  "success": true,
  "csrfToken": "서명된_토큰_문자열"
}
```

토큰은 자동으로 `csrf_token` 쿠키에 저장됩니다.

#### CSRF 검증 미들웨어

모든 POST/PUT/DELETE 요청에 자동으로 CSRF 토큰 검증이 적용됩니다:
- `/api/auth/login`
- `/api/auth/register`
- `/api/auth/logout`
- 기타 mutation 엔드포인트

**검증 로직:**
1. `X-CSRF-Token` 헤더에서 토큰 추출
2. `csrf_token` 쿠키에서 토큰 추출
3. 두 토큰 비교 (서명 검증 포함)
4. 만료 시간 확인 (1시간)

---

### 3. Frontend (React)

#### 자동 CSRF 토큰 포함

`fetchWithCsrf` 래퍼를 사용하면 자동으로 CSRF 토큰이 포함됩니다:

```typescript
import { fetchWithCsrf } from '@/lib/fetch-with-csrf';

// POST 요청 시 자동으로 X-CSRF-Token 헤더 추가
const response = await fetchWithCsrf('/api/auth/login', {
  method: 'POST',
  body: JSON.stringify({ email, password }),
});
```

#### CSRF 토큰 새로고침

```typescript
import { refreshCsrfToken } from '@/lib/fetch-with-csrf';

// 토큰 새로고침 (앱 초기화 시 또는 주기적으로)
await refreshCsrfToken();
```

---

## 사용 흐름

### 1. 앱 초기화 시

```typescript
// App 컴포넌트 또는 레이아웃
useEffect(() => {
  refreshCsrfToken();
}, []);
```

### 2. 로그인/회원가입

```typescript
import { login } from '@/lib/auth';

// fetchWithCsrf를 내부적으로 사용하여 자동 CSRF 토큰 포함
await login('user@example.com', 'password');
```

### 3. 기타 Mutation 요청

```typescript
const response = await fetchWithCsrf('/api/some-endpoint', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
});
```

---

## 보안 특징

### 1. Double Submit Cookie 패턴
- 쿠키와 헤더에 동일한 토큰 전송
- JavaScript로만 헤더 설정 가능
- 다른 도메인에서는 쿠키 읽기 불가

### 2. 서명 검증
- HMAC SHA-256 서명
- JWT_SECRET_KEY 사용
- 세션 ID와 연결

### 3. 토큰 만료
- 1시간 유효
- 타임스탬프 기반 검증

### 4. 타이밍 공격 방지
- `crypto.timingSafeEqual()` 사용 (Node.js)
- `hmac.compare_digest()` 사용 (Python)

---

## 테스트

### 단위 테스트 실행

```bash
cd neos
pytest tests/ -v
```

#### Security 테스트

```bash
pytest tests/test_security.py -v
```

**테스트 커버리지:**
- 비밀번호 해싱 및 검증
- 비밀번호 강도 검증
- API 키 생성 및 해싱
- 토큰 해싱
- 세션 ID 생성

#### JWT 테스트

```bash
pytest tests/test_jwt.py -v
```

**테스트 커버리지:**
- Access Token 생성 및 검증
- Refresh Token 생성 및 검증
- 토큰 만료 처리
- 토큰 타입 검증
- JWT ID (jti) 유니크성

#### API 통합 테스트

```bash
pytest tests/test_auth_api.py -v
```

**테스트 커버리지:**
- 회원가입 플로우
- 로그인 플로우
- 토큰 갱신
- 로그아웃
- API 키 관리
- CSRF 검증

---

### 테스트 실행 옵션

#### 특정 마커 테스트만 실행

```bash
# 단위 테스트만
pytest -m unit

# 통합 테스트만
pytest -m integration

# 느린 테스트 제외
pytest -m "not slow"
```

#### Coverage 리포트

```bash
pytest --cov=neos --cov-report=html tests/
```

HTML 리포트는 `htmlcov/index.html`에서 확인

#### 병렬 실행 (pytest-xdist 필요)

```bash
pytest -n auto tests/
```

---

## 테스트 구조

```
tests/
├── __init__.py
├── test_security.py       # Security 유틸리티 테스트
├── test_jwt.py            # JWT 유틸리티 테스트
└── test_auth_api.py       # Auth API 통합 테스트
```

---

## 예상 테스트 결과

### ✅ 성공 케이스
- 모든 단위 테스트 통과
- API 엔드포인트 정상 동작
- CSRF 검증 성공

### ❌ 실패 케이스 (의도된 동작)
- 약한 비밀번호 거부
- 만료된 토큰 거부
- CSRF 토큰 불일치 시 403 오류
- 중복 이메일 회원가입 거부

---

## 트러블슈팅

### CSRF 토큰 검증 실패

**증상:**
```
403 Forbidden - CSRF 토큰이 유효하지 않습니다.
```

**해결 방법:**
1. CSRF 토큰 새로고침
   ```typescript
   await refreshCsrfToken();
   ```

2. 쿠키 확인
   - 브라우저 개발자 도구 → Application → Cookies
   - `csrf_token` 쿠키 존재 확인

3. 헤더 확인
   - Network 탭에서 `X-CSRF-Token` 헤더 확인

### 테스트 데이터베이스 설정

통합 테스트 실행 전에 테스트 데이터베이스 설정:

```bash
# .env.test 파일 생성
DATABASE_URL=postgresql+asyncpg://user:password@localhost/neos_test

# 테스트 DB 마이그레이션
psql -U user -d neos_test -f neos/database/migrations/001_add_auth_tables.sql
```

### pytest-asyncio 설치

```bash
pip install pytest-asyncio httpx
```

---

## CSRF 토큰 라이프사이클

```
1. [Browser] 앱 로드
   ↓
2. [Frontend] refreshCsrfToken() 호출
   ↓
3. [BFF] GET /api/auth/csrf → 토큰 생성 및 쿠키 설정
   ↓
4. [Browser] csrf_token 쿠키 저장
   ↓
5. [Frontend] POST 요청 시 fetchWithCsrf 사용
   ↓
6. [JavaScript] 쿠키에서 토큰 읽어 X-CSRF-Token 헤더에 포함
   ↓
7. [BFF] CSRF 검증
   ↓
8. [Backend] 요청 처리
```

---

## Best Practices

### 1. 앱 초기화 시 CSRF 토큰 로드

```typescript
// app/layout.tsx
useEffect(() => {
  refreshCsrfToken();
}, []);
```

### 2. 모든 Mutation에 fetchWithCsrf 사용

```typescript
// ❌ 잘못된 방법
await fetch('/api/endpoint', { method: 'POST', body });

// ✅ 올바른 방법
await fetchWithCsrf('/api/endpoint', { method: 'POST', body });
```

### 3. 주기적 토큰 갱신 (선택)

```typescript
// 30분마다 토큰 갱신
setInterval(() => {
  refreshCsrfToken();
}, 30 * 60 * 1000);
```

### 4. 에러 처리

```typescript
try {
  const response = await fetchWithCsrf('/api/endpoint', {...});

  if (response.status === 403) {
    // CSRF 토큰 새로고침 후 재시도
    await refreshCsrfToken();
    return fetchWithCsrf('/api/endpoint', {...});
  }
} catch (error) {
  console.error('Request failed:', error);
}
```

---

## 참고 자료

- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Double Submit Cookie Pattern](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#double-submit-cookie)
- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
