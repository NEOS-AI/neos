/**
 * 백엔드 API 호출 유틸리티
 *
 * NextAuth 세션에서 백엔드 JWT 토큰을 가져와서
 * 백엔드 API를 호출하는 헬퍼 함수들
 */

import { auth } from "@/app/(auth)/auth";

export class BackendAPIError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public details?: any
  ) {
    super(message);
    this.name = "BackendAPIError";
  }
}

/**
 * 백엔드 API 호출
 *
 * @param endpoint - API 엔드포인트 (예: "/api/v1/votes")
 * @param options - fetch options
 * @returns Response 객체
 */
export async function callBackendAPI(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const session = await auth();

  if (!session?.backendAccessToken) {
    throw new BackendAPIError(
      "Unauthorized - No backend token",
      401,
      "NO_TOKEN"
    );
  }

  const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";
  const url = `${backendUrl}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.backendAccessToken}`,
      ...options.headers,
    },
  });

  // 401 에러 시 토큰 갱신 시도
  if (response.status === 401 && session.backendRefreshToken) {
    const newToken = await refreshBackendToken(session.backendRefreshToken);

    if (newToken) {
      // 새 토큰으로 재시도
      // Note: 세션 업데이트는 클라이언트에서 useSession().update() 호출 필요
      const retryResponse = await fetch(url, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${newToken}`,
          ...options.headers,
        },
      });

      return retryResponse;
    }
  }

  return response;
}

/**
 * 백엔드 Refresh Token으로 새 Access Token 발급
 *
 * @param refreshToken - Refresh token
 * @returns 새 access token 또는 null
 */
async function refreshBackendToken(
  refreshToken: string
): Promise<string | null> {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      return null;
    }

    const data = await response.json();
    return data.access_token;
  } catch (error) {
    console.error("Token refresh failed:", error);
    return null;
  }
}

/**
 * 백엔드 API 호출 후 JSON 파싱
 *
 * @param endpoint - API 엔드포인트
 * @param options - fetch options
 * @returns 파싱된 JSON 데이터
 */
export async function callBackendAPIWithJSON<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await callBackendAPI(endpoint, options);

  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: response.statusText,
    }));

    throw new BackendAPIError(
      error.detail || "Backend API call failed",
      response.status,
      error.code,
      error
    );
  }

  return response.json();
}

/**
 * API 키로 백엔드 API 호출 (서버 컴포넌트용)
 *
 * @param apiKey - API 키
 * @param endpoint - API 엔드포인트
 * @param options - fetch options
 * @returns Response 객체
 */
export async function callBackendAPIWithKey(
  apiKey: string,
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";
  const url = `${backendUrl}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
      ...options.headers,
    },
  });

  return response;
}
