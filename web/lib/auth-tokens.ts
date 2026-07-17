/**
 * 백엔드 토큰 갱신 응답 처리 (순수 로직)
 *
 * ## 백엔드 리프레시 토큰은 1회용이다
 *
 * - `neos/api/services/auth_service.py:209` — 조회 조건에 `~RefreshToken.is_used`
 * - `neos/api/services/auth_service.py:226` — 사용 즉시 `is_used = True` (회전)
 *
 * 즉 갱신 응답의 **새 refresh_token을 반드시 보존**해야 한다. 버리면 세션에는
 * 이미 소비된(is_used=True) 토큰만 남고, 다음 갱신이 401로 실패해
 * `RefreshAccessTokenError` → `useAuthMonitor`의 강제 로그아웃으로 이어진다.
 *
 * ## 갱신 경로는 하나뿐이어야 한다
 *
 * 1회용 토큰이므로 갱신 경로가 둘이면 **같은 토큰을 경쟁 소비**한다.
 * 과거 `lib/backend-api.ts`가 독자적으로 갱신하면서 회전된 토큰을 버렸고,
 * (서버 라우트 핸들러라 NextAuth 세션에 되쓸 방법도 없었다)
 * NextAuth `jwt` 콜백의 정기 갱신이 이미 소비된 토큰을 쓰게 만들었다.
 * 이제 갱신은 `app/(auth)/auth.ts`의 `jwt` 콜백 **한 곳**에서만 일어난다.
 */

/** 백엔드 `/api/v1/auth/refresh` 응답 (필요한 필드만) */
export type BackendRefreshResponse = {
  access_token?: unknown;
  refresh_token?: unknown;
  expires_in?: unknown;
};

export type BackendTokenState = {
  backendAccessToken?: string;
  backendRefreshToken?: string;
  accessTokenExpires?: number;
  error?: string;
};

/**
 * 액세스 토큰 기본 수명(ms).
 *
 * 백엔드가 `expires_in`(초)을 응답에 포함하므로
 * (`neos/api/models/auth_models.py:60`) 가능하면 그 값을 쓰고,
 * 없을 때만 이 기본값으로 폴백한다. 백엔드 기본 설정도 15분이다
 * (`config/neos.default.yaml:180`).
 */
export const DEFAULT_ACCESS_TOKEN_TTL_MS = 15 * 60 * 1000;

/** `expires_in`(초) → 만료 시각(ms). 값이 없거나 이상하면 기본 TTL로 폴백. */
export function resolveAccessTokenExpiry(
  expiresIn: unknown,
  now: number = Date.now()
): number {
  if (
    typeof expiresIn === "number" &&
    Number.isFinite(expiresIn) &&
    expiresIn > 0
  ) {
    return now + expiresIn * 1000;
  }
  return now + DEFAULT_ACCESS_TOKEN_TTL_MS;
}

/**
 * 갱신 응답을 기존 토큰 상태에 병합한다.
 *
 * - `access_token`이 없으면 갱신 실패로 간주한다.
 * - **회전된 `refresh_token`이 오면 반드시 그것으로 교체한다.**
 *   (백엔드가 회전을 생략하고 응답하지 않는 경우에만 기존 값을 유지)
 */
export function mergeRefreshedTokens<T extends BackendTokenState>(
  token: T,
  refreshed: BackendRefreshResponse,
  now: number = Date.now()
): T {
  if (typeof refreshed.access_token !== "string" || !refreshed.access_token) {
    throw new Error("Missing access_token");
  }

  const rotatedRefreshToken =
    typeof refreshed.refresh_token === "string" && refreshed.refresh_token
      ? refreshed.refresh_token
      : token.backendRefreshToken;

  return {
    ...token,
    backendAccessToken: refreshed.access_token,
    backendRefreshToken: rotatedRefreshToken,
    accessTokenExpires: resolveAccessTokenExpiry(refreshed.expires_in, now),
    error: undefined,
  };
}
