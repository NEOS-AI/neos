/**
 * 백엔드 API 호출 유틸리티 (**서버 전용**)
 *
 * NextAuth 세션에서 백엔드 JWT 토큰을 가져와서
 * 백엔드 API를 호출하는 헬퍼 함수들
 *
 * ## `import "server-only"` 를 스스로 단 이유
 *
 * 이 모듈은 `auth()` 와 `lib/server-config` 를 통해 이미 서버 전용이었지만
 * 그 사실을 **자기가 말하지 않았다.** 클라이언트 컴포넌트가 실수로 임포트하면
 * 빌드는 깨지되 오류가 `lib/server-config.ts:1` 을 가리켜, 정작 건드리면 안 되는
 * 모듈이 어느 것인지 말해주지 않았다(실제로 그 상태로 dev 에 남아 있었다).
 *
 * 명시적으로 달아 두면 위반 지점이 여기로 찍힌다. 클라이언트에서 부를 것은
 * `lib/ui-frame-client.ts` 처럼 **서버 임포트가 없는 모듈**에 둔다.
 */

import "server-only";

import { auth } from "@/app/(auth)/auth";
import { backendErrorCode, backendErrorMessage } from "@/lib/backend-error";
import { requestClientIpHeaders } from "@/lib/client-ip-server";
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
      // nginx 가 BFF IP 가 아니라 사용자 IP 로 rate limit 을 세도록 (`lib/client-ip.ts`)
      ...(await requestClientIpHeaders()),
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

    // `detail` 은 문자열·`{code, message}`·422 배열 중 하나다. 그대로 Error 에
    // 넣으면 뒤의 둘이 "[object Object]" 가 된다(`lib/backend-error.ts`).
    throw new BackendAPIError(
      backendErrorMessage(error, "Backend API call failed"),
      response.status,
      backendErrorCode(error),
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
      ...(await requestClientIpHeaders()),
      ...options.headers,
    },
  });

  return response;
}
