/**
 * Google OAuth 로그인 API Route (BFF)
 * - Google credential token을 백엔드로 전달
 * - 백엔드에서 받은 토큰을 Redis 세션에 저장
 * - HTTP-only 쿠키 설정
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { nanoid } from 'nanoid';
import { setSession } from '@/lib/redis';
import { validateCsrfToken, csrfErrorResponse } from '@/lib/csrf-validation';
import { rateLimitMiddleware, RATE_LIMIT_CONFIGS } from '@/lib/rate-limit';
import { BACKEND_URL } from '@/lib/env';

export async function POST(request: NextRequest) {
  // Rate Limiting 체크
  const { result, errorResponse } = await rateLimitMiddleware(
    request,
    RATE_LIMIT_CONFIGS.auth
  );

  if (errorResponse) {
    return errorResponse;
  }

  // CSRF 토큰 검증
  const isCsrfValid = await validateCsrfToken(request);
  if (!isCsrfValid) {
    return csrfErrorResponse();
  }

  try {
    const body = await request.json();
    const { google_token } = body;

    if (!google_token) {
      return NextResponse.json(
        { error: 'Google 토큰이 필요합니다.' },
        { status: 400 }
      );
    }

    // 백엔드 Google OAuth API 호출
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/oauth/google`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': request.headers.get('user-agent') || 'Next.js BFF',
      },
      body: JSON.stringify({ google_token }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      return NextResponse.json(
        { error: errorData.detail || 'Google 로그인에 실패했습니다.' },
        { status: response.status }
      );
    }

    const data = await response.json();
    const { access_token, refresh_token, user } = data;

    // 세션 ID 생성
    const sessionId = nanoid(32);

    // Redis에 세션 저장
    await setSession(
      sessionId,
      {
        accessToken: access_token,
        refreshToken: refresh_token,
        user,
        createdAt: new Date().toISOString(),
      },
      604800 // 7일
    );

    // HTTP-only 쿠키 설정
    const cookieStore = await cookies();
    cookieStore.set('neos_session', sessionId, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
      maxAge: 604800, // 7일
      path: '/',
    });

    return NextResponse.json({
      success: true,
      user,
    });
  } catch (error: any) {
    console.error('Google login error:', error);
    return NextResponse.json(
      { error: 'Google 로그인 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
