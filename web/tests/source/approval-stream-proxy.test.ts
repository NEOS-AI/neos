import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module from "node:module";
import path from "node:path";
import { before, beforeEach, describe, test } from "node:test";

/**
 * 승인 SSE 프록시 회귀 고정 (FE↔BE 감사 #8).
 *
 * 이 라우트(`app/(chat)/api/approval/stream/[sessionId]/route.ts`)는
 * `import "server-only"`를 문 `lib/backend-api.ts`를 임포트한다. 하지만
 * `tsconfig.test.json`이 tsx를 CJS로 에밋하게 만들기 때문에, 경로별칭을 포함한
 * 모든 first-party import(`@/lib/backend-api`도)가 `Module._load`를 거친다.
 * `@/lib/backend-api` 요청을 여기서 가로채면 임포트 체인이 그 지점에서
 * 끊기므로 `server-only`(그 아래에서 실제로 임포트되는 것)에는 아예 도달하지
 * 않는다. 형제 파일 `auth-login-expiry.test.ts:41-57`과 같은 기법이다.
 *
 * 이렇게 하면 라우트를 실제로 실행해 행동을 검증할 수 있다: signal 전달,
 * 상태 코드 통과, 스트림 본문 통과.
 */

// biome-ignore lint/suspicious/noExplicitAny: Node 내부 로더는 공개 타입이 없다
type CallBackendAPIStub = (endpoint: string, options: any) => Promise<Response>;

let capturedEndpoint: string | undefined;
// biome-ignore lint/suspicious/noExplicitAny: 캡처 대상은 fetch RequestInit 형태 그대로
let capturedOptions: any;
let stubResponse: Response;

const stubCallBackendAPI: CallBackendAPIStub = async (endpoint, options) => {
  capturedEndpoint = endpoint;
  capturedOptions = options;
  return stubResponse;
};

async function importRoute() {
  // biome-ignore lint/suspicious/noExplicitAny: Node 내부 로더는 공개 타입이 없다
  const ModuleAny = Module as any;
  const originalLoad = ModuleAny._load;
  // biome-ignore lint/suspicious/noExplicitAny: 위와 동일
  ModuleAny._load = (request: string, ...rest: any[]) => {
    if (request === "@/lib/backend-api") {
      return { callBackendAPI: stubCallBackendAPI };
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import(
      "../../app/(chat)/api/approval/stream/[sessionId]/route"
    );
  } finally {
    ModuleAny._load = originalLoad;
  }
}

// biome-ignore lint/suspicious/noExplicitAny: 동적 import 결과 형태를 미리 좁힐 수 없다
let route: any;

before(async () => {
  route = await importRoute();
});

beforeEach(() => {
  capturedEndpoint = undefined;
  capturedOptions = undefined;
});

test("maxDuration이 BE의 60초 컷보다 여유 있게 선언된다", () => {
  // BE는 세션 큐를 60.0초 타임아웃으로 자동 종료한다
  // (neos/api/handlers/approval_handlers.py:307, asyncio.wait_for timeout=60.0).
  const BE_TIMEOUT_SECONDS = 60;
  assert.ok(route.maxDuration > BE_TIMEOUT_SECONDS);
});

test("cacheComponents 빌드에서 금지된 `export const dynamic`을 쓰지 않는다", () => {
  // next.config.ts의 cacheComponents:true 아래에서 이 세그먼트 옵션은
  // "not compatible with nextConfig.cacheComponents" 빌드 오류다. 이건
  // Next.js 빌드 단계의 제약이라 node:test 실행으로는 검증할 수 없으므로
  // (실행 자체는 `dynamic` export 유무와 무관하게 성공한다), 여기만은
  // 소스 텍스트 검사로 남긴다.
  const routePath = path.resolve(
    import.meta.dirname,
    "../../app/(chat)/api/approval/stream/[sessionId]/route.ts"
  );
  const source = readFileSync(routePath, "utf8");
  const code = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
  assert.equal(
    /export const dynamic/.test(code),
    false,
    "이 라우트는 request.signal을 읽으므로 요청 시점 API 사용 자체로 이미 " +
      "동적이다 — `export const dynamic`을 따로 선언할 필요도, 여지도 없다"
  );
});

describe("GET /api/approval/stream/[sessionId]", () => {
  test("request.signal이 callBackendAPI 호출 옵션으로 전달된다 (취소 전파)", async () => {
    // 감사 #8: 탭을 닫아도 BE 제너레이터가 세션 큐를 계속 소비하던 버그.
    stubResponse = new Response(null, { status: 200 });
    const controller = new AbortController();
    const request = new Request("http://localhost/irrelevant", {
      signal: controller.signal,
    });

    await route.GET(request, { params: Promise.resolve({ sessionId: "s1" }) });

    assert.equal(capturedEndpoint, "/api/v1/approval/stream/s1");
    // `Request`가 넘겨받은 signal을 그대로 감싸므로(참조 동일성이 아니라
    // 전파로 확인해야 한다 -- Node의 fetch 구현이 새 AbortSignal 인스턴스를
    // 만들되 원본 신호를 따라가게 배선한다), 취소가 실제로 전파되는지로
    // 검증한다.
    assert.ok(capturedOptions?.signal instanceof AbortSignal);
    assert.equal(capturedOptions.signal.aborted, false);
    controller.abort();
    assert.equal(
      capturedOptions.signal.aborted,
      true,
      "callBackendAPI로 넘어간 signal이 원본 request.signal의 취소를 따라가지 않는다"
    );
  });

  test("세션 id를 URL에 인코딩해서 백엔드로 넘긴다", async () => {
    stubResponse = new Response(null, { status: 200 });
    const request = new Request("http://localhost/irrelevant");

    await route.GET(request, {
      params: Promise.resolve({ sessionId: "s 1/../x" }),
    });

    assert.equal(
      capturedEndpoint,
      `/api/v1/approval/stream/${encodeURIComponent("s 1/../x")}`
    );
  });

  test("백엔드가 비정상 응답이면 상태 코드와 본문을 그대로 전달한다", async () => {
    stubResponse = new Response(JSON.stringify({ detail: "session gone" }), {
      status: 404,
    });
    const request = new Request("http://localhost/irrelevant");

    const result = await route.GET(request, {
      params: Promise.resolve({ sessionId: "s1" }),
    });

    assert.equal(result.status, 404);
    assert.equal(await result.text(), JSON.stringify({ detail: "session gone" }));
  });

  test("백엔드가 정상 응답이면 text/event-stream으로 본문을 그대로 전달한다", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: completed\ndata: {"response": "ok"}\n\n'));
        controller.close();
      },
    });
    stubResponse = new Response(body, { status: 200 });
    const request = new Request("http://localhost/irrelevant");

    const result = await route.GET(request, {
      params: Promise.resolve({ sessionId: "s1" }),
    });

    assert.equal(result.status, 200);
    assert.equal(result.headers.get("Content-Type"), "text/event-stream");
    assert.equal(result.headers.get("Cache-Control"), "no-cache");
    assert.equal(result.headers.get("Connection"), "keep-alive");
    assert.equal(result.headers.get("X-Accel-Buffering"), "no");

    const text = await result.text();
    assert.equal(text, 'event: completed\ndata: {"response": "ok"}\n\n');
  });
});
