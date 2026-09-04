import { strict as assert } from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module from "node:module";
import { before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { DEFAULT_ACCESS_TOKEN_TTL_MS } from "../../lib/auth-tokens";

/**
 * 회귀 테스트: 로그인이 `expires_in`을 버린다 (#7)
 *
 * BE `TokenResponse`는 `expires_in`(초)을 항상 포함한다
 * (`neos/api/models/auth_models.py:60`). 갱신 경로(`mergeRefreshedTokens` →
 * `resolveAccessTokenExpiry`)는 그것을 쓰는데, 로그인 세 경로
 * (credentials `authorize()`, guest `authorize()`, google `signIn`)는
 * `Date.now() + DEFAULT_ACCESS_TOKEN_TTL_MS`로 하드코딩되어 있었다.
 * 배포가 `auth.access_token_expire_minutes`를 15가 아닌 값으로 두면
 * 그 차이만큼 FE가 만료된 토큰으로 계속 요청을 보낸다.
 *
 * `auth.ts`의 `jwt` 콜백은 NextAuth 내부 배선이라 직접 호출할 수 없어서,
 * 만료 시각을 고르는 부분만 순수 함수(`computeAccessTokenExpiry`)로 뺐다.
 * 실제 TTL "계산"은 여기서도 새로 하지 않는다 — 전부
 * `lib/auth-tokens.ts`의 `resolveAccessTokenExpiry`에 위임한다
 * (이 파일이 그 헬퍼 자체를 검증하지는 않는다 — 그건 `auth-tokens.test.ts` 몫이다).
 */

/**
 * `auth.ts`는 `lib/server-config.ts`를 거쳐 `server-only` 패키지를 import한다.
 * 그 패키지는 Next.js 클라이언트 번들 오용을 막으려고 평범한 Node `require`에서도
 * 무조건 던진다 (웹팩의 `react-server` export 조건에서만 빈 모듈로 리다이렉트되는데,
 * 이 테스트 러너 `tsx --test`는 그 조건을 세팅하지 않는다). 그래서 `auth.ts`를 그냥
 * import하면 이 테스트 프로세스 자체가 죽는다 — `auth-tokens.test.ts`의
 * "갱신 경로 단일화" 테스트가 auth.ts를 import 대신 `readFileSync`로 읽는 것도
 * 같은 이유다.
 *
 * 여기서는 `auth.ts`가 내보내는 순수 함수의 실제 동작을 값으로 고정해야 하므로,
 * import 직전에만 Node CJS 로더를 가로채 `server-only` 요청을 빈 객체로
 * 바꿔치기하고 곧바로 원상복구한다. 프로덕션 코드는 건드리지 않는다 —
 * 이 테스트 프로세스의 모듈 해석 한 번만 우회할 뿐이다.
 */
async function importAuthModule() {
  // biome-ignore lint/suspicious/noExplicitAny: Node 내부 로더는 공개 타입이 없다
  const ModuleAny = Module as any;
  const originalLoad = ModuleAny._load;
  // biome-ignore lint/suspicious/noExplicitAny: 위와 동일
  ModuleAny._load = (request: string, ...rest: any[]) => {
    if (request === "server-only") {
      return {};
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import("../../app/(auth)/auth");
  } finally {
    ModuleAny._load = originalLoad;
  }
}

// biome-ignore lint/suspicious/noExplicitAny: 동적 import 결과 형태를 미리 좁힐 수 없다
let authModule: any;

before(async () => {
  authModule = await importAuthModule();
});

describe("extractBackendTokenFields — 세 로그인 경로가 공유하는 추출기", () => {
  test("일반 로그인 응답에서 expires_in을 그대로 옮긴다", () => {
    const fields = authModule.extractBackendTokenFields({
      access_token: "acc",
      refresh_token: "ref",
      expires_in: 1800,
    });

    assert.equal(fields.backendAccessToken, "acc");
    assert.equal(fields.backendRefreshToken, "ref");
    assert.equal(fields.expiresIn, 1800);
  });

  test("게스트 로그인 응답에서도 동일하게 옮긴다", () => {
    const fields = authModule.extractBackendTokenFields({
      access_token: "guest-acc",
      refresh_token: "guest-ref",
      expires_in: 600,
    });

    assert.equal(fields.backendAccessToken, "guest-acc");
    assert.equal(fields.backendRefreshToken, "guest-ref");
    assert.equal(fields.expiresIn, 600);
  });

  test("구글 OAuth 응답에서도 동일하게 옮긴다", () => {
    const fields = authModule.extractBackendTokenFields({
      access_token: "google-acc",
      refresh_token: "google-ref",
      expires_in: 3600,
    });

    assert.equal(fields.backendAccessToken, "google-acc");
    assert.equal(fields.backendRefreshToken, "google-ref");
    assert.equal(fields.expiresIn, 3600);
  });

  test("expires_in이 응답에 없으면 undefined로 통과시킨다 (계산은 하지 않는다)", () => {
    const fields = authModule.extractBackendTokenFields({
      access_token: "acc",
      refresh_token: "ref",
    });

    assert.equal(fields.expiresIn, undefined);
  });
});

describe("computeAccessTokenExpiry — 로그인/가입 시점 (user가 있음)", () => {
  test("BE가 준 expires_in이 만료 시각에 반영된다", () => {
    const expires = authModule.computeAccessTokenExpiry({
      user: { expiresIn: 3600 },
      now: 0,
    });

    assert.equal(expires, 3_600_000);
  });

  test("expires_in이 없으면 15분 기본값으로 떨어진다", () => {
    const expires = authModule.computeAccessTokenExpiry({
      user: {},
      now: 0,
    });

    assert.equal(expires, DEFAULT_ACCESS_TOKEN_TTL_MS);
  });

  test("expires_in이 0이면 15분 기본값으로 떨어진다", () => {
    const expires = authModule.computeAccessTokenExpiry({
      user: { expiresIn: 0 },
      now: 0,
    });

    assert.equal(expires, DEFAULT_ACCESS_TOKEN_TTL_MS);
  });

  test("expires_in이 음수면 15분 기본값으로 떨어진다", () => {
    const expires = authModule.computeAccessTokenExpiry({
      user: { expiresIn: -5 },
      now: 0,
    });

    assert.equal(expires, DEFAULT_ACCESS_TOKEN_TTL_MS);
  });

  test("expires_in이 비수치면 15분 기본값으로 떨어진다", () => {
    const expires = authModule.computeAccessTokenExpiry({
      user: { expiresIn: "nope" },
      now: 0,
    });

    assert.equal(expires, DEFAULT_ACCESS_TOKEN_TTL_MS);
  });

  test("세 로그인 경로 전부: BE 응답 → 추출 → 만료 계산이 일관되게 이어진다", () => {
    const loginShapes = [
      { access_token: "a", refresh_token: "r", expires_in: 120 },
      { access_token: "a", refresh_token: "r", expires_in: 240 },
      { access_token: "a", refresh_token: "r", expires_in: 480 },
    ];

    for (const data of loginShapes) {
      const user = authModule.extractBackendTokenFields(data);
      const expires = authModule.computeAccessTokenExpiry({ user, now: 0 });
      assert.equal(expires, data.expires_in * 1000);
    }
  });
});

describe("computeAccessTokenExpiry — 세션 갱신 시점 (user가 없음)", () => {
  // fix round 1: `computeAccessTokenExpiry`에서 `trigger` 파라미터를 없앴다
  // (안 읽는 파라미터를 안전하지 않은 방식으로 "읽게" 만드는 대신 삭제 --
  // 분기는 여전히 `params.user`의 truthiness만 본다). `jwt` 콜백 쪽의
  // `trigger === "update"` 게이트는 그대로 남아 있다 -- 이 함수를 호출할지
  // 말지를 결정할 뿐, 넘기는 인자 모양에는 관여하지 않는다.
  test("세션이 expiresIn을 실어 오면 그 값을 쓴다", () => {
    const expires = authModule.computeAccessTokenExpiry({
      session: { expiresIn: 7200 },
      now: 0,
    });

    assert.equal(expires, 7_200_000);
  });

  test("세션에 값이 없으면 15분 기본값으로 폴백한다 (이 경로엔 BE 응답이 없다)", () => {
    const expires = authModule.computeAccessTokenExpiry({
      session: undefined,
      now: 0,
    });

    assert.equal(expires, DEFAULT_ACCESS_TOKEN_TTL_MS);
  });
});

describe("구조 회귀: 하드코딩 TTL이 세 로그인 경로 중 하나로도 되돌아오지 않는다", () => {
  const source = readFileSync(
    fileURLToPath(new URL("../../app/(auth)/auth.ts", import.meta.url)),
    "utf8"
  );

  test("jwt 콜백이 더 이상 Date.now() + DEFAULT_ACCESS_TOKEN_TTL_MS를 쓰지 않는다", () => {
    assert.ok(
      !source.includes("Date.now() + DEFAULT_ACCESS_TOKEN_TTL_MS"),
      "하드코딩 15분 TTL이 되돌아왔다 — resolveAccessTokenExpiry를 우회하고 있다"
    );
  });

  test("credentials, guest, google 세 경로 각각이 공유 추출기를 호출한다 (이름으로 확인 — 개수만 세지 않는다)", () => {
    const loginIdx = source.indexOf("/api/v1/auth/login");
    const guestIdx = source.indexOf("/api/v1/auth/guest");
    const googleIdx = source.indexOf("/api/v1/auth/oauth/google");

    assert.ok(loginIdx >= 0, "credentials 로그인 경로를 찾지 못했다");
    assert.ok(guestIdx >= 0, "guest 로그인 경로를 찾지 못했다");
    assert.ok(googleIdx >= 0, "google OAuth 경로를 찾지 못했다");

    // 세 경로는 이 순서로 파일에 등장한다: credentials → guest → google.
    const credentialsBlock = source.slice(loginIdx, guestIdx);
    const guestBlock = source.slice(guestIdx, googleIdx);
    const googleBlock = source.slice(googleIdx);

    assert.ok(
      credentialsBlock.includes("extractBackendTokenFields(data)"),
      "credentials authorize()가 공유 추출기를 쓰지 않는다"
    );
    assert.ok(
      guestBlock.includes("extractBackendTokenFields(data)"),
      "guest authorize()가 공유 추출기를 쓰지 않는다"
    );
    assert.ok(
      googleBlock.includes("extractBackendTokenFields(data)"),
      "google signIn이 공유 추출기를 쓰지 않는다"
    );
  });
});
