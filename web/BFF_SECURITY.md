# NEOS BFF 인증 레이어 보안 가이드

## 개요

NEOS 웹 애플리케이션은 BFF (Backend For Frontend) 패턴을 사용하여 프론트엔드와 백엔드 사이에 보안 레이어를 구현합니다.

## 아키텍처

```
[Browser] <-> [Next.js BFF] <-> [FastAPI Backend]
```

### 주요 구성 요소

1. **인증 프록시**: 모든 인증 요청은 BFF를 통해 백엔드로 전달
2. **세션 관리**: Redis 기반 서버 사이드 세션
3. **CSRF 보호**: Double Submit Cookie 패턴
4. **Rate Limiting**: IP 기반 요청 제한
5. **보안 헤더**: CSP, HSTS 등

## 보안 기능

### 1. 환경 변수 검증 ✅

**파일**: `web/lib/env.ts`

필수 환경 변수가 설정되지 않으면 서버 시작 실패:

```typescript
// .env.local 필수 설정
JWT_SECRET_KEY=<안전한-시크릿-키>
BACKEND_URL=http://localhost:8518
REDIS_URL=redis://localhost:6379
```

**위험한 기본값 감지**:
- "your-secret-key-change-this"
- "change-this"
- "secret"
- "password"
- "test"

### 2. CSRF 보호 ✅

**파일**:
- `web/lib/csrf.ts` - 토큰 생성/검증
- `web/lib/csrf-validation.ts` - API route 검증
- `web/lib/fetch-with-csrf.ts` - 클라이언트 자동 포함

**구현 방식**:
- Double Submit Cookie 패턴
- HMAC 서명 토큰 (세션 바인딩)
- 타이밍 공격 방지 (timingSafeEqual)
- 자동 갱신 및 재시도

**사용 예시**:
```typescript
// 서버 사이드 (API Route)
const isCsrfValid = await validateCsrfToken(request);
if (!isCsrfValid) {
  return csrfErrorResponse();
}

// 클라이언트 사이드
import { fetchWithCsrf } from '@/lib/fetch-with-csrf';

const response = await fetchWithCsrf('/api/auth/login', {
  method: 'POST',
  body: JSON.stringify({ email, password }),
});
```

### 3. 세션 관리 ✅

**파일**:
- `web/lib/redis.ts` - Redis 클라이언트 및 세션 CRUD
- `web/lib/session-validation.ts` - 세션 검증 유틸리티

**특징**:
- Redis 서버 사이드 세션
- HTTP-only 쿠키 (XSS 방지)
- SameSite=strict (CSRF 추가 방어)
- 7일 만료 정책
- 세션 ID: nanoid(32)

**에러 처리**:
```typescript
// Redis 연결 실패와 세션 없음을 구분
try {
  const session = await getSession(sessionId);
} catch (error) {
  if (error instanceof RedisConnectionError) {
    // 503 Service Unavailable
    // 세션을 삭제하지 않음 (Redis 복구 후 계속 사용 가능)
  }
}
```

### 4. 토큰 갱신 ✅

**파일**: `web/app/api/auth/refresh/route.ts`

**구현**:
- Access Token 만료 시 자동 갱신
- Refresh Token rotation
- `/api/auth/me`에서 자동 갱신 로직 포함

**흐름**:
1. Access Token으로 API 요청
2. 401 Unauthorized 응답
3. Refresh Token으로 새 토큰 요청
4. Redis 세션 업데이트
5. 갱신된 토큰으로 재시도

### 5. Rate Limiting ✅

**파일**: `web/lib/rate-limit.ts`

**알고리즘**: Sliding Window (Redis Sorted Set)

**설정**:
```typescript
export const RATE_LIMIT_CONFIGS = {
  // 로그인/회원가입: 15분에 5회
  auth: {
    windowSeconds: 900,
    maxRequests: 5,
  },

  // 일반 API: 1분에 60회
  api: {
    windowSeconds: 60,
    maxRequests: 60,
  },

  // CSRF 토큰: 1분에 10회
  csrf: {
    windowSeconds: 60,
    maxRequests: 10,
  },
};
```

**적용된 엔드포인트**:
- `/api/auth/login`
- `/api/auth/register`

**응답 헤더**:
```
HTTP/1.1 429 Too Many Requests
Retry-After: 300
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 300
```

### 6. 보안 헤더 ✅

**파일**: `web/middleware.ts`

**적용된 헤더**:

| 헤더 | 값 | 목적 |
|------|-----|------|
| X-Content-Type-Options | nosniff | MIME 타입 스니핑 방지 |
| X-Frame-Options | DENY | 클릭재킹 방지 |
| X-XSS-Protection | 1; mode=block | XSS 필터 활성화 |
| Referrer-Policy | strict-origin-when-cross-origin | Referer 제어 |
| Permissions-Policy | camera=(), microphone=(), geolocation=() | 기능 제한 |
| Strict-Transport-Security | max-age=31536000; includeSubDomains; preload | HTTPS 강제 (프로덕션) |
| Content-Security-Policy | default-src 'self'; ... | XSS 및 인젝션 방지 |

### 7. 로깅 시스템 ✅

**파일**: `web/lib/logger.ts`

**기능**:
- 환경별 로그 형식 (개발: 읽기 쉬운 형식, 프로덕션: JSON)
- 민감 정보 자동 마스킹
- 구조화된 로그

**민감 필드 목록**:
- password, token, accessToken, refreshToken
- apiKey, secret, authorization, cookie

**사용 예시**:
```typescript
import { logger, createLogger } from '@/lib/logger';

// 기본 로거
logger.info('User logged in', { userId: 'user_123' });
logger.error('Login failed', error, { email: 'user@example.com' });

// 컨텍스트별 로거
const authLogger = createLogger('Auth');
authLogger.warn('Multiple login attempts', { ip: '192.168.1.1' });
```

### 8. Middleware 세션 검증 ✅

**파일**: `web/middleware.ts`

**제약사항**:
- Edge Runtime에서는 Redis 연결 불가능
- 따라서 쿠키 존재 여부만 확인

**상세 검증**:
- 각 API route에서 `validateSession()` 사용
- Redis 세션 유효성 확인
- 필수 필드 검증 (accessToken, refreshToken)

### 9. 세션 고정 공격 방어 ✅

**방어 메커니즘**:
1. 로그인 시 새 세션 ID 생성 (`nanoid(32)`)
2. 기존 세션 무효화 (새 세션으로 덮어쓰기)
3. HTTP-only 쿠키로 클라이언트 접근 불가

**코드**: `web/app/api/auth/login/route.ts:51-73`

## API 엔드포인트

### 인증 API

| 엔드포인트 | 메서드 | 설명 | 보호 |
|-----------|--------|------|------|
| `/api/auth/login` | POST | 로그인 | CSRF, Rate Limit |
| `/api/auth/register` | POST | 회원가입 | CSRF, Rate Limit |
| `/api/auth/logout` | POST | 로그아웃 | CSRF, Session |
| `/api/auth/refresh` | POST | 토큰 갱신 | Session |
| `/api/auth/me` | GET | 사용자 정보 | Session |
| `/api/auth/csrf` | GET | CSRF 토큰 | - |

## 디렉토리 구조

```
web/
├── app/
│   └── api/
│       └── auth/
│           ├── login/route.ts       # 로그인 API
│           ├── logout/route.ts      # 로그아웃 API
│           ├── register/route.ts    # 회원가입 API
│           ├── refresh/route.ts     # 토큰 갱신 API
│           ├── me/route.ts          # 사용자 정보 API
│           └── csrf/route.ts        # CSRF 토큰 API
├── lib/
│   ├── env.ts                       # 환경 변수 검증
│   ├── csrf.ts                      # CSRF 토큰 생성/검증
│   ├── csrf-validation.ts           # CSRF API route 헬퍼
│   ├── fetch-with-csrf.ts           # 클라이언트 CSRF 래퍼
│   ├── redis.ts                     # Redis 클라이언트
│   ├── session-validation.ts        # 세션 검증 유틸리티
│   ├── rate-limit.ts                # Rate Limiting
│   ├── logger.ts                    # 로깅 시스템
│   └── auth.ts                      # 인증 클라이언트 유틸리티
└── middleware.ts                    # Next.js Middleware (세션 체크, 보안 헤더)
```

## 환경 설정

### 개발 환경

```bash
# .env.local
JWT_SECRET_KEY=development-secret-key-min-32-chars
BACKEND_URL=http://localhost:8518
REDIS_URL=redis://localhost:6379
NODE_ENV=development
```

### 프로덕션 환경

```bash
# .env.production
JWT_SECRET_KEY=<강력한-랜덤-키-64자-이상>
BACKEND_URL=https://api.neos.ai
REDIS_URL=redis://redis.production:6379
NODE_ENV=production
```

**JWT_SECRET_KEY 생성**:
```bash
openssl rand -base64 64
```

## 보안 체크리스트

### 배포 전 확인 사항

- [ ] JWT_SECRET_KEY 설정 (64자 이상)
- [ ] 프로덕션 환경에서 안전하지 않은 기본값 제거
- [ ] Redis 연결 보안 (TLS, 인증)
- [ ] HTTPS 적용 (HSTS 활성화)
- [ ] CSP 정책 검토 및 조정
- [ ] Rate Limiting 설정 검토
- [ ] 로그 모니터링 설정

### 정기 점검 사항

- [ ] 세션 만료 정책 검토 (현재: 7일)
- [ ] CSRF 토큰 만료 정책 검토 (현재: 1시간)
- [ ] Access Token 만료 (현재: 15분)
- [ ] Refresh Token 만료 (현재: 7일)
- [ ] Rate Limiting 임계값 조정
- [ ] 보안 헤더 업데이트

## 테스트

### 단위 테스트

```bash
cd web
npm run test
```

### 통합 테스트

```bash
# Backend API 테스트
cd ../
pytest tests/test_auth_api.py -v

# BFF 테스트 (TODO)
cd web
npm run test:integration
```

## 문제 해결

### Redis 연결 오류

**증상**: 모든 인증 요청이 실패

**해결**:
```bash
# Redis 상태 확인
redis-cli ping

# Redis 재시작
sudo systemctl restart redis
```

**코드 동작**:
- Redis 연결 실패 시 503 Service Unavailable 반환
- 세션 쿠키는 삭제하지 않음 (Redis 복구 후 계속 사용 가능)

### CSRF 토큰 오류

**증상**: 403 Forbidden (INVALID_CSRF_TOKEN)

**원인**:
1. CSRF 토큰 만료 (1시간)
2. 쿠키와 헤더 불일치
3. 크로스 도메인 요청

**해결**:
- 자동 갱신 활성화 (fetchWithCsrf 사용)
- `/api/auth/csrf` 호출하여 새 토큰 발급

### Rate Limit 초과

**증상**: 429 Too Many Requests

**해결**:
```typescript
// Retry-After 헤더 확인
const retryAfter = response.headers.get('Retry-After');
setTimeout(() => retry(), parseInt(retryAfter) * 1000);
```

## 추가 개선사항

### 단기 (1-2주)

- [ ] BFF 통합 테스트 추가
- [ ] 에러 핸들링 표준화
- [ ] API 응답 타입 정의

### 중기 (1개월)

- [ ] 세션 클러스터링 (Redis Sentinel/Cluster)
- [ ] 분산 Rate Limiting
- [ ] 로그 집계 시스템 (ELK, Datadog)

### 장기 (3개월)

- [ ] 2FA (Two-Factor Authentication)
- [ ] Device Fingerprinting
- [ ] Anomaly Detection

## 참고 자료

- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [Next.js Security Best Practices](https://nextjs.org/docs/app/building-your-application/configuring/security-headers)
