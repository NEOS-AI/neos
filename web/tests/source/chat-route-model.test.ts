import assert from "node:assert/strict";
import Module from "node:module";
import { before, beforeEach, describe, test } from "node:test";

/**
 * 회귀 고정: 매 메시지가 매핑 안 된 게이트웨이 모델 ID를 백엔드로 보낸다 (#6).
 *
 * `route.ts:88`(대화 생성)은 `mapToBackendModelName(selectedChatModel)`을 쓰는데,
 * `:138`(매 메시지 스트림 요청)은 원본 `selectedChatModel`(Vercel AI Gateway id,
 * 예: "anthropic/claude-sonnet-5")을 그대로 실어 보냈다. BE가 그 값을 읽더라도
 * 카탈로그의 실제 모델명이 아니므로 동작하지 않는다.
 *
 * 이 라우트(`app/(chat)/api/chat/route.ts`)는 `@/lib/backend-api`를 거쳐
 * `server-only`에 닿는다. `@/lib/backend-api` 요청을 여기서 가로채면 임포트
 * 체인이 그 지점에서 끊기므로 `server-only`에는 아예 도달하지 않는다.
 * `@/app/(auth)/auth` 요청도 같은 이유로 가로챈다(세션이 필요하기 때문).
 * 형제 파일 `approval-stream-proxy.test.ts`, `auth-login-expiry.test.ts:41-57`과
 * 같은 기법이다.
 */

type CallBackendAPIStub = (endpoint: string, options?: any) => Promise<Response>;

let capturedStreamEndpoint: string | undefined;
let capturedStreamBody: any;

const BACKEND_USER_ID = "backend-user-1";
const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";

const stubCallBackendAPI: CallBackendAPIStub = async (endpoint, options) => {
  if (endpoint.includes("/message-count")) {
    return new Response(null, { status: 503 });
  }
  if (
    endpoint === `/api/v1/chat/conversations/${CONVERSATION_ID}` &&
    (!options || options.method === undefined)
  ) {
    // 기존 conversation 조회 — 있다고 답해 생성 분기(및 title 생성)를 건너뛴다.
    return new Response(
      JSON.stringify({ conversation_id: CONVERSATION_ID, user_id: BACKEND_USER_ID }),
      { status: 200 }
    );
  }
  if (endpoint === `/api/v1/chat/conversations/${CONVERSATION_ID}/messages/stream`) {
    capturedStreamEndpoint = endpoint;
    capturedStreamBody = JSON.parse((options?.body as string) ?? "{}");
    return new Response(null, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  }
  throw new Error(`unexpected callBackendAPI endpoint in test: ${endpoint}`);
};

const stubAuth = async () => ({
  user: {
    id: BACKEND_USER_ID,
    type: "regular",
    backendUserId: BACKEND_USER_ID,
  },
});

async function importRoute() {
  const ModuleAny = Module as any;
  const originalLoad = ModuleAny._load;
  ModuleAny._load = (request: string, ...rest: any[]) => {
    if (request === "@/lib/backend-api") {
      return { callBackendAPI: stubCallBackendAPI };
    }
    if (request === "@/app/(auth)/auth") {
      return { auth: stubAuth };
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import("../../app/(chat)/api/chat/route");
  } finally {
    ModuleAny._load = originalLoad;
  }
}

let route: any;

before(async () => {
  route = await importRoute();
});

beforeEach(() => {
  capturedStreamEndpoint = undefined;
  capturedStreamBody = undefined;
});

function buildRequest(selectedChatModel: string): Request {
  const body = {
    id: CONVERSATION_ID,
    message: {
      id: "22222222-2222-4222-8222-222222222222",
      role: "user",
      parts: [{ type: "text", text: "hello" }],
    },
    selectedChatModel,
    selectedVisibilityType: "private",
  };
  return new Request("http://localhost/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/chat — 매 메시지 metadata.model", () => {
  test("현역 게이트웨이 id는 매핑된 백엔드 모델명으로 나간다", async () => {
    const response = await route.POST(buildRequest("anthropic/claude-sonnet-5"));

    assert.equal(response.status, 200);
    assert.equal(capturedStreamEndpoint, `/api/v1/chat/conversations/${CONVERSATION_ID}/messages/stream`);
    assert.equal(
      capturedStreamBody.metadata.model,
      "claude-sonnet-5",
      "매핑되지 않은 원본 게이트웨이 id가 그대로 나가면 안 된다"
    );
  });

  test("은퇴한 게이트웨이 id도 RETIRED_MODEL_MAP을 거쳐 나간다 (쿠키에 남은 옛 선택)", async () => {
    const response = await route.POST(buildRequest("anthropic/claude-opus-4.5"));

    assert.equal(response.status, 200);
    assert.equal(
      capturedStreamBody.metadata.model,
      "claude-opus-5",
      "은퇴한 모델 id가 매핑 없이 그대로 나가면 BE 카탈로그에 없는 이름이 도달한다"
    );
  });
});
