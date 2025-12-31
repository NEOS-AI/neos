# Google OAuth 설정 가이드

## 1. Google Cloud Console 설정

### 1.1 OAuth 동의 화면 구성
1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 좌측 메뉴 > **API 및 서비스** > **OAuth 동의 화면**
3. User Type 선택: **외부** (모든 Google 계정 사용자)
4. 앱 정보 입력:
   - 앱 이름: `Neos`
   - 사용자 지원 이메일: 본인 이메일
   - 개발자 연락처: 본인 이메일
5. 범위(Scopes) 추가:
   - `userinfo.email`
   - `userinfo.profile`
   - `openid`

### 1.2 OAuth 클라이언트 ID 생성
1. 좌측 메뉴 > **API 및 서비스** > **사용자 인증 정보**
2. **+ 사용자 인증 정보 만들기** > **OAuth 클라이언트 ID**
3. 애플리케이션 유형: **웹 애플리케이션**
4. 이름: `Neos Web Client`
5. **승인된 자바스크립트 원본** 추가:
   - 개발: `http://localhost:3000`
   - 프로덕션: `https://yourdomain.com`
6. **승인된 리디렉션 URI** 추가:
   - 개발: `http://localhost:3000/api/auth/callback/google`
   - 프로덕션: `https://yourdomain.com/api/auth/callback/google`
7. **만들기** 클릭
8. **클라이언트 ID**와 **클라이언트 보안 비밀번호** 복사

## 2. 환경 변수 설정

### 2.1 프론트엔드 (.env)
```bash
# web/.env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-client-secret
```

### 2.2 백엔드 (.env)
```bash
# .env (프로젝트 루트)
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
```

**중요:** 프론트엔드와 백엔드의 Client ID는 동일해야 합니다.

## 3. 테스트

### 3.1 개발 환경 테스트
1. 백엔드 실행: `make dev` 또는 `python -m neos.main`
2. 프론트엔드 실행: `cd web && npm run dev`
3. http://localhost:3000/login 접속
4. "Google로 로그인" 버튼 클릭
5. Google 계정 선택 및 권한 승인

### 3.2 예상 동작
- 신규 사용자: 자동 가입 후 대시보드로 이동
- 기존 사용자: 즉시 로그인
- 이메일 중복: "이 이메일로 가입된 계정이 있습니다" 에러

## 4. 보안 주의사항

1. **Client Secret 관리**
   - `.env` 파일은 절대 Git에 커밋하지 마세요
   - 프로덕션 환경에서는 Secret Manager 사용 권장

2. **리디렉션 URI 화이트리스트**
   - Google Cloud Console에 등록된 URI만 허용됨
   - 프로덕션 배포 전 실제 도메인 추가 필수

3. **HTTPS 사용**
   - 프로덕션 환경에서는 반드시 HTTPS 사용
   - 개발 환경에서만 HTTP 허용
