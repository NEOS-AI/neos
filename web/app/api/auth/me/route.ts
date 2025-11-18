/**
 * 현재 사용자 정보 조회 API Route
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { getSession, setSession } from '@/lib/redis';
import { BACKEND_URL } from '@/lib/env';

export async function GET(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const sessionId = cookieStore.get('neos_session')?.value;

    if (!sessionId) {
      return NextResponse.json(
        { error: '로그인이 필요합니다.' },
        { status: 401 }
      );
    }

    // Redis에서 세션 가져오기
    const session = await getSession(sessionId);

    if (!session || !session.accessToken) {
      // 세션이 만료되었거나 유효하지 않음
      cookieStore.delete('neos_session');
      return NextResponse.json(
        { error: '세션이 만료되었습니다.' },
        { status: 401 }
      );
    }

    // 백엔드에서 사용자 정보 조회
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${session.accessToken}`,
      },
    });

    if (!response.ok) {
      // Access Token이 만료된 경우 갱신 시도
      if (response.status === 401 && session.refreshToken) {
        try {
          // 백엔드 토큰 갱신 API 호출
          const refreshResponse = await fetch(`${BACKEND_URL}/api/v1/auth/refresh`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ refresh_token: session.refreshToken }),
          });

          if (!refreshResponse.ok) {
            // Refresh Token도 만료된 경우
            cookieStore.delete('neos_session');
            return NextResponse.json(
              { error: '인증이 만료되었습니다. 다시 로그인해주세요.' },
              { status: 401 }
            );
          }

          const refreshData = await refreshResponse.json();
          const { access_token, refresh_token, user } = refreshData;

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

          // 갱신된 토큰으로 다시 사용자 정보 조회
          const retryResponse = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${access_token}`,
            },
          });

          if (!retryResponse.ok) {
            return NextResponse.json(
              { error: '사용자 정보를 가져올 수 없습니다.' },
              { status: retryResponse.status }
            );
          }

          const retryUser = await retryResponse.json();

          return NextResponse.json({
            success: true,
            user: retryUser,
            tokenRefreshed: true,
          });
        } catch (refreshError) {
          console.error('Token refresh error:', refreshError);
          cookieStore.delete('neos_session');
          return NextResponse.json(
            { error: '인증이 만료되었습니다. 다시 로그인해주세요.' },
            { status: 401 }
          );
        }
      }

      return NextResponse.json(
        { error: '사용자 정보를 가져올 수 없습니다.' },
        { status: response.status }
      );
    }

    const user = await response.json();

    return NextResponse.json({
      success: true,
      user,
    });
  } catch (error: any) {
    console.error('Get user error:', error);
    return NextResponse.json(
      { error: '사용자 정보 조회 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
