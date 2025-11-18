/**
 * 로그아웃 API Route
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { getSession, deleteSession } from '@/lib/redis';
import { validateCsrfToken, csrfErrorResponse } from '@/lib/csrf-validation';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8518';

export async function POST(request: NextRequest) {
  // CSRF 토큰 검증
  const isCsrfValid = await validateCsrfToken(request);
  if (!isCsrfValid) {
    return csrfErrorResponse();
  }

  try {
    const cookieStore = await cookies();
    const sessionId = cookieStore.get('neos_session')?.value;

    if (!sessionId) {
      return NextResponse.json(
        { error: '로그인되어 있지 않습니다.' },
        { status: 401 }
      );
    }

    // Redis에서 세션 가져오기
    const session = await getSession(sessionId);

    if (session && session.refreshToken) {
      // 백엔드 로그아웃 API 호출 (Refresh Token 무효화)
      try {
        await fetch(`${BACKEND_URL}/api/v1/auth/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ refresh_token: session.refreshToken }),
        });
      } catch (error) {
        console.error('Backend logout error:', error);
        // 백엔드 에러는 무시하고 계속 진행
      }
    }

    // Redis에서 세션 삭제
    await deleteSession(sessionId);

    // 쿠키 삭제
    cookieStore.delete('neos_session');

    return NextResponse.json({
      success: true,
      message: '로그아웃되었습니다.',
    });
  } catch (error: any) {
    console.error('Logout error:', error);
    return NextResponse.json(
      { error: '로그아웃 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
