/**
 * 토큰 갱신 API Route
 * - Access Token이 만료되었을 때 Refresh Token으로 갱신
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { getSession, setSession } from '@/lib/redis';
import { BACKEND_URL } from '@/lib/env';

export async function POST(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const sessionId = cookieStore.get('neos_session')?.value;

    if (!sessionId) {
      return NextResponse.json(
        { error: '세션이 존재하지 않습니다.' },
        { status: 401 }
      );
    }

    // Redis에서 세션 가져오기
    const session = await getSession(sessionId);

    if (!session || !session.refreshToken) {
      // 세션이 만료되었거나 유효하지 않음
      cookieStore.delete('neos_session');
      return NextResponse.json(
        { error: '세션이 만료되었습니다. 다시 로그인해주세요.' },
        { status: 401 }
      );
    }

    // 백엔드 토큰 갱신 API 호출
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: session.refreshToken }),
    });

    if (!response.ok) {
      const errorData = await response.json();

      // Refresh Token도 만료된 경우
      if (response.status === 401) {
        cookieStore.delete('neos_session');
        return NextResponse.json(
          { error: 'Refresh Token이 만료되었습니다. 다시 로그인해주세요.' },
          { status: 401 }
        );
      }

      return NextResponse.json(
        { error: errorData.detail || '토큰 갱신에 실패했습니다.' },
        { status: response.status }
      );
    }

    const data = await response.json();
    const { access_token, refresh_token, user } = data;

    // Redis 세션 업데이트
    await setSession(
      sessionId,
      {
        accessToken: access_token,
        refreshToken: refresh_token,
        user,
        createdAt: session.createdAt,
        lastRefreshed: new Date().toISOString(),
      },
      604800 // 7일
    );

    return NextResponse.json({
      success: true,
      message: '토큰이 갱신되었습니다.',
      user,
    });
  } catch (error: any) {
    console.error('Token refresh error:', error);
    return NextResponse.json(
      { error: '토큰 갱신 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
