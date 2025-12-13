/**
 * 현재 사용자 정보 조회 API Route
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { deleteSession } from '@/lib/redis';
import { getValidAccessToken } from '@/lib/session-helper';
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

    // 유효한 Access Token 가져오기 (자동 갱신 포함)
    const tokenResult = await getValidAccessToken(sessionId);

    if (!tokenResult) {
      // 세션이 만료되었거나 갱신 실패
      cookieStore.delete('neos_session');
      await deleteSession(sessionId);
      return NextResponse.json(
        { error: '인증이 만료되었습니다. 다시 로그인해주세요.' },
        { status: 401 }
      );
    }

    // 백엔드에서 사용자 정보 조회
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${tokenResult.accessToken}`,
      },
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: '사용자 정보를 가져올 수 없습니다.' },
        { status: response.status }
      );
    }

    const user = await response.json();

    return NextResponse.json({
      success: true,
      user,
      tokenRefreshed: tokenResult.wasRefreshed,
    });
  } catch (error: any) {
    console.error('Get user error:', error);
    return NextResponse.json(
      { error: '사용자 정보 조회 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
