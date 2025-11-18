/**
 * Next.js Middleware
 * - 기본 인증 체크 (쿠키 존재 여부)
 * - 보안 헤더 추가
 * - 상세 세션 검증은 각 API route 및 Server Component에서 수행
 *
 * 참고: Edge Runtime 제약사항
 * - Redis 연결 불가능 (Node.js 런타임 필요)
 * - 따라서 여기서는 기본적인 쿠키 검증만 수행
 * - 실제 세션 유효성은 lib/session-validation.ts 사용
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// 보호된 경로 정의
const protectedPaths = ['/chat', '/dashboard', '/settings', '/api/proxy'];

// 공개 경로 정의
const publicPaths = ['/login', '/register', '/', '/api/auth'];

/**
 * 보안 헤더 추가
 */
function addSecurityHeaders(response: NextResponse): NextResponse {
  // X-Content-Type-Options: MIME 타입 스니핑 방지
  response.headers.set('X-Content-Type-Options', 'nosniff');

  // X-Frame-Options: 클릭재킹 방지
  response.headers.set('X-Frame-Options', 'DENY');

  // X-XSS-Protection: XSS 필터 활성화 (레거시 브라우저용)
  response.headers.set('X-XSS-Protection', '1; mode=block');

  // Referrer-Policy: Referer 헤더 제어
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');

  // Permissions-Policy: 브라우저 기능 제한
  response.headers.set(
    'Permissions-Policy',
    'camera=(), microphone=(), geolocation=()'
  );

  // HSTS (Strict-Transport-Security): HTTPS 강제 (프로덕션만)
  if (process.env.NODE_ENV === 'production') {
    response.headers.set(
      'Strict-Transport-Security',
      'max-age=31536000; includeSubDomains; preload'
    );
  }

  // Content-Security-Policy: XSS 및 데이터 인젝션 공격 방지
  // 참고: 실제 CSP는 앱의 요구사항에 맞게 조정 필요
  const cspHeader = `
    default-src 'self';
    script-src 'self' 'unsafe-eval' 'unsafe-inline';
    style-src 'self' 'unsafe-inline';
    img-src 'self' data: https:;
    font-src 'self' data:;
    connect-src 'self';
    frame-ancestors 'none';
  `.replace(/\s{2,}/g, ' ').trim();

  response.headers.set('Content-Security-Policy', cspHeader);

  return response;
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // API auth routes는 항상 허용
  if (pathname.startsWith('/api/auth')) {
    const response = NextResponse.next();
    return addSecurityHeaders(response);
  }

  // 공개 경로는 항상 허용
  if (publicPaths.some((path) => pathname === path || pathname.startsWith(path))) {
    const response = NextResponse.next();
    return addSecurityHeaders(response);
  }

  // 보호된 경로 체크
  const isProtectedPath = protectedPaths.some(
    (path) => pathname === path || pathname.startsWith(path)
  );

  if (isProtectedPath) {
    const sessionCookie = request.cookies.get('neos_session');

    if (!sessionCookie) {
      // 세션 쿠키가 없으면 로그인 페이지로 리다이렉트
      const url = request.nextUrl.clone();
      url.pathname = '/login';
      url.searchParams.set('redirect', pathname);
      const response = NextResponse.redirect(url);
      return addSecurityHeaders(response);
    }

    // 참고: 세션의 실제 유효성(Redis 검증)은 각 경로에서
    // lib/session-validation.ts의 validateSession() 사용
  }

  const response = NextResponse.next();
  return addSecurityHeaders(response);
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
