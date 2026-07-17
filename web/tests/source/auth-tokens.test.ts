import { strict as assert } from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_ACCESS_TOKEN_TTL_MS,
  mergeRefreshedTokens,
  resolveAccessTokenExpiry,
} from "../../lib/auth-tokens";

/**
 * 회귀 테스트: 리프레시 토큰 회전 파괴 → 무작위 강제 로그아웃
 * (FE_AUDIT_260717 §3.3)
 *
 * 백엔드 리프레시 토큰은 1회용이다(`auth_service.py:209,226` — `~is_used` 조회 조건 +
 * 사용 즉시 `is_used = True`). 갱신 응답의 새 refresh_token을 버리면 세션에는
 * 이미 소비된 토큰만 남아 다음 갱신이 반드시 실패한다.
 */
describe("백엔드 토큰 갱신 병합", () => {
  const baseToken = {
    backendAccessToken: "old-access",
    backendRefreshToken: "old-refresh",
    accessTokenExpires: 1000,
  };

  test("회전된 refresh_token을 반드시 보존한다 (버리면 다음 갱신이 죽는다)", () => {
    const merged = mergeRefreshedTokens(
      baseToken,
      {
        access_token: "new-access",
        refresh_token: "rotated-refresh",
        expires_in: 900,
      },
      0
    );

    assert.equal(merged.backendAccessToken, "new-access");
    // 핵심 단언: 소비된 old-refresh가 남아 있으면 안 된다
    assert.equal(merged.backendRefreshToken, "rotated-refresh");
    assert.notEqual(merged.backendRefreshToken, "old-refresh");
  });

  test("갱신 성공 시 이전 error 상태를 해제한다", () => {
    const merged = mergeRefreshedTokens(
      { ...baseToken, error: "RefreshAccessTokenError" },
      { access_token: "new-access", refresh_token: "r2", expires_in: 900 },
      0
    );

    assert.equal(merged.error, undefined);
  });

  test("백엔드가 refresh_token을 생략하면 기존 값을 유지한다", () => {
    const merged = mergeRefreshedTokens(
      baseToken,
      { access_token: "new-access", expires_in: 900 },
      0
    );

    assert.equal(merged.backendRefreshToken, "old-refresh");
  });

  test("access_token이 없으면 갱신 실패로 처리한다", () => {
    assert.throws(
      () => mergeRefreshedTokens(baseToken, { refresh_token: "r" }, 0),
      // biome-ignore lint/performance/useTopLevelRegex: 단언 1회용 리터럴
      /Missing access_token/
    );
  });

  test("만료 시각은 백엔드 expires_in을 따른다 (하드코딩 15분이 아니라)", () => {
    // 백엔드 expires_in은 설정 가능하다 (config/neos.default.yaml:180)
    const merged = mergeRefreshedTokens(
      baseToken,
      { access_token: "a", refresh_token: "r", expires_in: 3600 },
      0
    );

    assert.equal(merged.accessTokenExpires, 3_600_000);
  });

  test("expires_in이 없거나 이상하면 기본 TTL로 폴백한다", () => {
    assert.equal(
      resolveAccessTokenExpiry(undefined, 0),
      DEFAULT_ACCESS_TOKEN_TTL_MS
    );
    assert.equal(resolveAccessTokenExpiry(0, 0), DEFAULT_ACCESS_TOKEN_TTL_MS);
    assert.equal(resolveAccessTokenExpiry(-5, 0), DEFAULT_ACCESS_TOKEN_TTL_MS);
    assert.equal(
      resolveAccessTokenExpiry("nope", 0),
      DEFAULT_ACCESS_TOKEN_TTL_MS
    );
  });
});

/**
 * 구조적 회귀 테스트: 갱신 경로는 **하나**여야 한다.
 *
 * 1회용 토큰이므로 갱신 경로가 둘이면 같은 토큰을 경쟁 소비한다.
 * 이 테스트는 `/api/v1/auth/refresh` 호출이 auth.ts 밖으로 다시 새는 것을 막는다.
 */
describe("갱신 경로 단일화", () => {
  const read = (relativePath: string) =>
    readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8");

  test("lib/backend-api.ts는 토큰을 직접 갱신하지 않는다", () => {
    const source = read("../../lib/backend-api.ts");

    // 주석에는 경로가 언급될 수 있으므로 실제 fetch 호출 형태를 검사한다.
    // biome-ignore lint/suspicious/noTemplateCurlyInString: 소스 텍스트를 문자 그대로 검사한다
    const refreshCall = "`${backendUrl}/api/v1/auth/refresh`";

    assert.ok(
      !source.includes(refreshCall),
      "backend-api.ts가 다시 토큰 갱신을 시도하고 있다 — 1회용 토큰을 경쟁 소비해 강제 로그아웃을 유발한다"
    );
  });

  test("auth.ts가 갱신을 담당하며 회전 토큰 보존 로직을 쓴다", () => {
    const source = read("../../app/(auth)/auth.ts");

    assert.ok(source.includes("/api/v1/auth/refresh"));
    assert.ok(
      source.includes("mergeRefreshedTokens"),
      "auth.ts가 회전 토큰 보존 로직을 우회하고 있다"
    );
  });
});
