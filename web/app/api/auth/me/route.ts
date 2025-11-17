/**
 * 현재 사용자 정보 조회 API Route
 */
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { getSession } from '@/lib/redis';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8518';

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
        // TODO: 토큰 갱신 로직 (별도 엔드포인트로 분리 가능)
        return NextResponse.json(
          { error: '인증이 만료되었습니다. 다시 로그인해주세요.' },
          { status: 401 }
        );
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
