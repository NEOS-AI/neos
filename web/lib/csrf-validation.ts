/**
 * CSRF 검증 헬퍼
 */
import { NextRequest } from 'next/server';
import { cookies } from 'next/headers';
import { verifyCsrfToken, verifySignedCsrfToken } from './csrf';

const CSRF_SECRET = process.env.JWT_SECRET_KEY || 'your-secret-key-change-this';

/**
 * CSRF 토큰 검증
 *
 * @param request NextRequest 객체
 * @returns 유효성 여부
 */
export async function validateCsrfToken(request: NextRequest): Promise<boolean> {
  try {
    // GET 요청은 CSRF 검증 불필요
    if (request.method === 'GET') {
      return true;
    }

    // CSRF 토큰 가져오기 (헤더 또는 쿠키)
    const csrfTokenFromHeader = request.headers.get('x-csrf-token');
    const cookieStore = await cookies();
    const csrfTokenFromCookie = cookieStore.get('csrf_token')?.value;

    if (!csrfTokenFromHeader || !csrfTokenFromCookie) {
      console.warn('CSRF token missing');
      return false;
    }

    // 세션 ID 가져오기
    const sessionId = cookieStore.get('neos_session')?.value;

    if (sessionId) {
      // 서명된 토큰 검증
      return verifySignedCsrfToken(
        csrfTokenFromHeader,
        sessionId,
        CSRF_SECRET,
        3600000 // 1시간
      );
    } else {
      // 단순 토큰 검증
      return verifyCsrfToken(csrfTokenFromHeader, csrfTokenFromCookie);
    }
  } catch (error) {
    console.error('CSRF validation error:', error);
    return false;
  }
}

/**
 * CSRF 검증 실패 응답
 */
export function csrfErrorResponse() {
  return new Response(
    JSON.stringify({
      error: 'CSRF 토큰이 유효하지 않습니다.',
      code: 'INVALID_CSRF_TOKEN',
    }),
    {
      status: 403,
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );
}
