import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

/**
 * 승인 SSE 프록시 회귀 고정 (FE↔BE 감사 #8).
 *
 * 이 라우트(`app/(chat)/api/approval/stream/[sessionId]/route.ts`)는
 * `import "server-only"`를 문 `lib/backend-api.ts`를 임포트한다. `server-only`
 * 패키지는 실행 환경을 가리지 않고 **임포트되는 순간 무조건 던진다**
 * (`node_modules/server-only/index.js` — `typeof window` 체크조차 없다).
 * Next.js 빌드는 서버 컴포넌트 그래프에서 이 파일을 조건부 export("react-server")로
 * 갈아치우지만, `tsx --test`는 그 스왑을 하지 않으므로 이 라우트를 (또는 그
 * 안의 어떤 named export든) import하면 그 순간 이 파일이 아니라 임포트 체인
 * 전체가 죽는다.
 *
 * `node:test`의 `mock.module`로 `@/lib/backend-api`를 대역으로 바꿔치면 우회할
 * 수 있지만, 그 API는 `--experimental-test-module-mocks` 없이는 존재하지 않고
 * (직접 확인: 이 저장소의 `pnpm test:source`는 그 플래그를 켜지 않는다),
 * 그 플래그를 이 파일 하나만을 위해 켜려면 공유 스크립트(`package.json`의
 * `test:source`)를 고쳐야 한다 — 이 작업의 소유 파일이 아니고, 다른 모든
 * 테스트 파일의 실행 방식을 바꾸는 부수효과가 생긴다.
 *
 * 그래서 형제 파일 `deep-analysis-subscription.test.ts`의
 * "이벤트 프록시 라우트는 GET만 노출한다" 테스트와 같은 패턴 — 소스 텍스트
 * 회귀 고정 — 을 쓴다. 실행 검증이 아니라 정적 검증이라는 한계는 있지만,
 * 이 라우트가 순수 바이트 파이프(파싱 없음)라는 제약과 맞물려 실질적으로
 * 놓치는 것이 적다: 여기서 고정하는 네 가지(신호 전달, 상태 코드 통과,
 * dynamic 미선언, maxDuration 여유값)는 전부 문자 그대로의 소스 형태로
 * 드러나는 회귀들이다.
 */

const ROUTE_PATH = path.resolve(
  import.meta.dirname,
  "../../app/(chat)/api/approval/stream/[sessionId]/route.ts"
);

const source = readFileSync(ROUTE_PATH, "utf8");
// 주석 속에 우연히 패턴이 등장해 오탐하는 것을 막는다.
const code = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

const SIGNAL_FORWARDED =
  /callBackendAPI\(\s*`[^`]*`\s*,\s*\{\s*signal:\s*request\.signal\s*,?\s*\}\s*\)/;
const DYNAMIC_EXPORT = /export const dynamic/;
const MAX_DURATION = /export const maxDuration\s*=\s*(\d+)/;
const STATUS_PASSTHROUGH = /status:\s*backendResponse\.status/;
const UNUSED_REQUEST_PARAM = /_request\s*:\s*Request/;
const BE_TIMEOUT_SECONDS = 60;

test("request.signal이 callBackendAPI 호출 옵션으로 전달된다 (취소 전파)", () => {
  // 감사 #8: 탭을 닫아도 BE 제너레이터가 세션 큐를 계속 소비하던 버그.
  // 형제 라우트(`deep-analysis/[runId]/events/route.ts:50`)와 같은 방식.
  assert.match(
    code,
    SIGNAL_FORWARDED,
    "request.signal이 callBackendAPI 옵션으로 전달되지 않는다 — " +
      "구독을 끊어도 백엔드 호출이 계속된다"
  );
});

test("GET의 request 파라미터가 실제로 쓰인다 (밑줄-미사용 회귀 금지)", () => {
  assert.equal(
    UNUSED_REQUEST_PARAM.test(code),
    false,
    "GET가 request를 여전히 `_request`로 버리고 있다 — signal을 전달할 수 없다"
  );
});

test("백엔드가 비정상 응답이면 상태 코드를 그대로 전달한다 (기존 동작 유지)", () => {
  assert.match(code, STATUS_PASSTHROUGH);
});

test("cacheComponents 빌드에서 금지된 `export const dynamic`을 쓰지 않는다", () => {
  // next.config.ts의 cacheComponents:true 아래에서 이 세그먼트 옵션은
  // "not compatible with nextConfig.cacheComponents" 빌드 오류다.
  assert.equal(
    DYNAMIC_EXPORT.test(code),
    false,
    "이 라우트는 request.signal을 읽으므로 요청 시점 API 사용 자체로 이미 " +
      "동적이다 — `export const dynamic`을 따로 선언할 필요도, 여지도 없다"
  );
});

test("maxDuration이 BE의 60초 컷보다 여유 있게 선언된다", () => {
  // BE는 세션 큐를 60.0초 타임아웃으로 자동 종료한다
  // (neos/api/handlers/approval_handlers.py:307, asyncio.wait_for timeout=60.0).
  // 이 라우트의 실제 상한은 그 60초이지, 형제(job 스트림, 300초)의 상한이 아니다.
  const match = code.match(MAX_DURATION);
  assert.ok(match, "maxDuration이 선언되지 않았다");
  const value = Number(match?.[1]);
  assert.ok(
    value > BE_TIMEOUT_SECONDS,
    `maxDuration(${value}s)이 BE 타임아웃(${BE_TIMEOUT_SECONDS}s)보다 크지 않다`
  );
});
