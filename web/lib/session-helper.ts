/**
 * 세션 관리 헬퍼 유틸리티
 * - JWT 토큰 자동 갱신
 * - 세션 검증 및 관리
 */
import { cookies } from 'next/headers';
import { NextRequest } from 'next/server';
import { getSession, setSession, deleteSession } from './redis';
import { BACKEND_URL } from './env';

/**
 * JWT 토큰의 만료 시간을 확인
 * @param token JWT 토큰
 * @returns 만료 여부 (true: 만료됨, false: 유효함)
 */
function isTokenExpired(token: string): boolean {
  try {
    // JWT는 "header.payload.signature" 형식
    const parts = token.split('.');
    if (parts.length !== 3) {
      return true; // 잘못된 형식
    }

    // Payload를 base64 디코딩
    const payload = JSON.parse(
      Buffer.from(parts[1], 'base64').toString('utf-8')
    );

    // exp 필드 확인 (초 단위 Unix timestamp)
    if (!payload.exp) {
      return true; // exp 없으면 만료로 간주
    }

    // 현재 시간과 비교 (30초 버퍼 추가)
    const now = Math.floor(Date.now() / 1000);
    const expiresAt = payload.exp;

    return now >= expiresAt - 30; // 30초 전부터 만료로 간주
  } catch (error) {
    console.error('Error checking token expiration:', error);
    return true; // 에러 발생 시 만료로 간주
  }
}

/**
 * Refresh Token으로 새 Access Token 발급
 * @param refreshToken Refresh Token
 * @returns 새로운 Access Token과 Refresh Token
 */
async function refreshTokens(refreshToken: string): Promise<{
  access_token: string;
  refresh_token: string;
  user: any;
} | null> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      console.error(
        `Token refresh failed: ${response.status} ${response.statusText}`
      );
      return null;
    }

    const data = await response.json();
    return {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: data.user,
    };
  } catch (error) {
    console.error('Error refreshing tokens:', error);
    return null;
  }
}

/**
 * 세션에서 유효한 Access Token 가져오기 (자동 갱신 포함)
 * @param sessionId 세션 ID
 * @returns Access Token과 갱신 여부
 */
export async function getValidAccessToken(sessionId: string): Promise<{
  accessToken: string;
  wasRefreshed: boolean;
} | null> {
  try {
    // Redis에서 세션 가져오기
    const session = await getSession(sessionId);

    if (!session || !session.accessToken || !session.refreshToken) {
      console.error('Session not found or invalid');
      return null;
    }

    // Access Token이 아직 유효한지 확인
    if (!isTokenExpired(session.accessToken)) {
      return {
        accessToken: session.accessToken,
        wasRefreshed: false,
      };
    }

    // Access Token이 만료됨 -> Refresh Token으로 갱신
    console.log(`[Session] Access token expired, refreshing: ${sessionId}`);
    const refreshResult = await refreshTokens(session.refreshToken);

    if (!refreshResult) {
      console.error('Failed to refresh tokens');
      return null;
    }

    // 갱신된 토큰을 Redis에 저장
    await setSession(
      sessionId,
      {
        accessToken: refreshResult.access_token,
        refreshToken: refreshResult.refresh_token,
        user: refreshResult.user,
        createdAt: session.createdAt,
        lastRefreshed: new Date().toISOString(),
      },
      604800 // 7일
    );

    console.log(`[Session] Tokens refreshed successfully: ${sessionId}`);

    return {
      accessToken: refreshResult.access_token,
      wasRefreshed: true,
    };
  } catch (error) {
    console.error('Error getting valid access token:', error);
    return null;
  }
}

/**
 * Authorization 헤더를 자동으로 추가하는 fetch 래퍼
 * @param url 요청 URL
 * @param options fetch 옵션
 * @param sessionId 세션 ID
 * @returns fetch Response
 */
export async function fetchWithAuth(
  url: string,
  options: RequestInit,
  sessionId: string
): Promise<Response> {
  // 유효한 Access Token 가져오기 (자동 갱신 포함)
  const tokenResult = await getValidAccessToken(sessionId);

  if (!tokenResult) {
    throw new Error('Failed to get valid access token');
  }

  // Authorization 헤더 추가
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${tokenResult.accessToken}`);

  return fetch(url, {
    ...options,
    headers,
  });
}

/**
 * 요청에서 세션 검증 및 반환
 * @param request Next.js Request 객체
 * @returns 세션 객체 및 세션 ID
 */
export async function requireSession(
  request: NextRequest
): Promise<{ session: any; sessionId: string } | null> {
  try {
    const cookieStore = await cookies();
    const sessionId = cookieStore.get('neos_session')?.value;

    if (!sessionId) {
      console.error('[Session] No session cookie found');
      return null;
    }

    // Redis에서 세션 가져오기
    const session = await getSession(sessionId);

    if (!session) {
      console.error('[Session] Session not found in Redis');
      cookieStore.delete('neos_session');
      return null;
    }

    // 필수 필드 검증
    if (!session.accessToken || !session.refreshToken) {
      console.error('[Session] Session missing required fields');
      cookieStore.delete('neos_session');
      await deleteSession(sessionId);
      return null;
    }

    return { session, sessionId };
  } catch (error) {
    console.error('[Session] Error validating session:', error);
    return null;
  }
}
