/**
 * CSRF 토큰 발급 API
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { generateCsrfToken, createSignedCsrfToken } from '@/lib/csrf';
import { getSession } from '@/lib/redis';
import { JWT_SECRET_KEY } from '@/lib/env';

export async function GET(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const sessionId = cookieStore.get('neos_session')?.value;

    let csrfToken: string;

    if (sessionId) {
      // 세션이 있으면 서명된 토큰 생성
      csrfToken = createSignedCsrfToken(sessionId, JWT_SECRET_KEY);
    } else {
      // 세션이 없으면 단순 토큰 생성
      csrfToken = generateCsrfToken();
    }

    // CSRF 토큰을 쿠키에 저장 (JavaScript에서 읽을 수 있어야 함)
    cookieStore.set('csrf_token', csrfToken, {
      httpOnly: false, // JavaScript에서 읽을 수 있어야 함
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
      maxAge: 3600, // 1시간
      path: '/',
    });

    return NextResponse.json({
      success: true,
      csrfToken,
    });
  } catch (error: any) {
    console.error('CSRF token generation error:', error);
    return NextResponse.json(
      { error: 'CSRF 토큰 생성 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
