/**
 * Next.js Middleware
 * - 인증 체크
 * - CSRF 보호 (향후 추가)
 * - Rate Limiting (향후 추가)
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// 보호된 경로 정의
const protectedPaths = ['/chat', '/dashboard', '/settings', '/api/proxy'];

// 공개 경로 정의
const publicPaths = ['/login', '/register', '/', '/api/auth'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // API auth routes는 항상 허용
  if (pathname.startsWith('/api/auth')) {
    return NextResponse.next();
  }

  // 공개 경로는 항상 허용
  if (publicPaths.some((path) => pathname === path || pathname.startsWith(path))) {
    return NextResponse.next();
  }

  // 보호된 경로 체크
  const isProtectedPath = protectedPaths.some(
    (path) => pathname === path || pathname.startsWith(path)
  );

  if (isProtectedPath) {
    const sessionCookie = request.cookies.get('neos_session');

    if (!sessionCookie) {
      // 세션이 없으면 로그인 페이지로 리다이렉트
      const url = request.nextUrl.clone();
      url.pathname = '/login';
      url.searchParams.set('redirect', pathname);
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.next();
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
