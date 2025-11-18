/**
 * 로그인 API Route
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { nanoid } from 'nanoid';
import { setSession } from '@/lib/redis';
import { validateCsrfToken, csrfErrorResponse } from '@/lib/csrf-validation';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8518';

export async function POST(request: NextRequest) {
  // CSRF 토큰 검증
  const isCsrfValid = await validateCsrfToken(request);
  if (!isCsrfValid) {
    return csrfErrorResponse();
  }

  try {
    const body = await request.json();
    const { email, password } = body;

    if (!email || !password) {
      return NextResponse.json(
        { error: '이메일과 비밀번호를 입력해주세요.' },
        { status: 400 }
      );
    }

    // 백엔드 로그인 API 호출
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': request.headers.get('user-agent') || 'Next.js BFF',
      },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      return NextResponse.json(
        { error: errorData.detail || '로그인에 실패했습니다.' },
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
    console.error('Login error:', error);
    return NextResponse.json(
      { error: '로그인 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
