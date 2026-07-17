/**
 * 백엔드 API 호출 유틸리티
 *
 * NextAuth 세션에서 백엔드 JWT 토큰을 가져와서
 * 백엔드 API를 호출하는 헬퍼 함수들
 */

import { auth } from "@/app/(auth)/auth";
import { getBackendUrl } from "@/lib/server-config";

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

  const backendUrl = getBackendUrl();
  const url = `${backendUrl}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.backendAccessToken}`,
      ...options.headers,
    },
  });

  // ⚠️ 여기서 토큰을 갱신하지 말 것.
  //
  // 백엔드 리프레시 토큰은 1회용이다(`auth_service.py:209,226`).
  // 과거 이 지점에서 독자적으로 `/api/v1/auth/refresh`를 호출했으나,
  //   ① 회전된 새 refresh_token을 버렸고,
  //   ② 서버 라우트 핸들러라 NextAuth 세션에 되쓸 방법이 없었다.
  // 결과적으로 세션에는 이미 소비된(is_used=True) 토큰만 남아
  // NextAuth `jwt` 콜백의 다음 갱신이 401 → RefreshAccessTokenError →
  // `useAuthMonitor`의 무작위 강제 로그아웃으로 이어졌다.
  //
  // 갱신은 `app/(auth)/auth.ts`의 `jwt` 콜백이 단독으로 담당한다. 이 콜백은
  // 만료 5분 전부터 선제적으로 갱신하므로(`auth.ts`), `auth()`를 거치는 이 함수는
  // 이미 유효한 액세스 토큰을 받는다. 401이 남는다면 그것은 실제 인증 실패이며,
  // 호출자에게 그대로 전달해야 한다.
  return response;
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
  const backendUrl = getBackendUrl();
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

/**
 * Phase 8 (A2UI): UI 폼 제출 — 서버사이드 Route Handler를 거쳐 백엔드로 전달
 *
 * POST /api/v1/ui/submit 은 인증 토큰이 필요하므로,
 * Next.js Route Handler (/api/ui-submit) 경유 방식을 사용한다.
 * 클라이언트 컴포넌트에서 직접 호출 가능.
 */
export async function submitUIFrameClient(
  frameId: string,
  sessionId: string,
  values: Record<string, unknown>,
  conversationId?: string
): Promise<Response> {
  const response = await fetch("/api/ui-submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      frame_id: frameId,
      session_id: sessionId,
      values,
      conversation_id: conversationId,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `UI submit failed (${response.status})`);
  }

  // 호출자가 SSE 스트림을 직접 읽음
  return response;
}
