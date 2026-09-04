// DOM 전역을 **먼저** 세운다 -- `tests/dom-setup.ts` 상단 주석 참조.
import "../dom-setup";
import assert from "node:assert/strict";
import Module from "node:module";
import { afterEach, before, test } from "node:test";
import type { UseChatHelpers } from "@ai-sdk/react";
import { act } from "react";
import type { ChatMessage } from "../../lib/types";
import { renderComponent } from "../render";

/**
 * 회귀 고정 (Task 3b + fix round 1 finding 1): 승인 실패 메시지가 화면에
 * 도달하지 않는다.
 *
 * 두 실패 지점이 같은 증상을 냈다:
 * - resume 스트림이 종결 `error` 이벤트로 끝나는 경우(`respondToApproval`의
 *   catch가 `error.message`를 버렸다 -- 3b).
 * - `POST /api/approval/respond` 자체가 비정상 응답인 경우
 *   (`app/(chat)/api/approval/respond/route.ts:12-16`가 `{ error: <사유> }`를
 *   실어 보내는데, `respondToApproval`이 그 본문을 읽지 않고 정적 문구
 *   "Approval response failed"로 갈아치웠다 -- fix round 1 finding 1).
 *
 * 두 경로 다 백엔드가 준 이유가 카드에 그대로 보여야 한다.
 */

/**
 * `message.tsx`는 정적으로 두 가지를 끌어들이는데 둘 다 이 테스트가
 * 실제로 쓰지 않는다:
 *
 * - `./message-editor` → `@/app/(chat)/actions`(서버 액션) → `server-only`.
 *   `message-editor-attachments.test.tsx`와 같은 기법.
 * - `./document-preview` → `./sheet-editor` → `react-data-grid`의 CSS.
 *   `tsx --test`는 순수 CJS 로더라 `.css` 임포트를 이해하지 못해
 *   `SyntaxError: Invalid or unexpected token`으로 죽는다 -- 이 테스트가
 *   건드리는 approval 카드와는 무관한 경로다.
 *
 * 두 요청만 가로채고 나머지는 원래 로더로 그대로 넘긴다.
 */
async function importPreviewMessage() {
  const ModuleAny = Module as any;
  const originalLoad = ModuleAny._load;
  ModuleAny._load = (request: string, ...rest: any[]) => {
    if (request === "@/app/(chat)/actions") {
      return {
        deleteTrailingMessages: () => {
          // 이 테스트는 편집(삭제) 흐름을 쓰지 않는다 -- 임포트 체인만 끊으면 된다.
        },
      };
    }
    if (request === "./document-preview") {
      return { DocumentPreview: () => null };
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import("../../components/message");
  } finally {
    ModuleAny._load = originalLoad;
  }
}

let messageModule: any;
let dataStreamModule: any;

before(async () => {
  messageModule = await importPreviewMessage();
  dataStreamModule = await import("../../components/data-stream-provider");
});

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

/** resume 스트림이 종결 `error` 이벤트로 끝나는 경로만 실패시킨다 (respond 자체는 200). */
function stubFetchWithStreamError(errorMessage: string) {
  globalThis.fetch = ((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.startsWith("/api/approval/respond")) {
      return Promise.resolve(new Response(null, { status: 200 }));
    }
    if (url.startsWith("/api/approval/stream/")) {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              `event: error\ndata: ${JSON.stringify({ message: errorMessage })}\n\n`
            )
          );
          controller.close();
        },
      });
      return Promise.resolve(new Response(body, { status: 200 }));
    }
    throw new Error(`이 테스트가 예상하지 못한 fetch: ${url}`);
  }) as typeof fetch;
}

/**
 * `POST /api/approval/respond` 자체가 비정상 응답으로 실패한다 -- 백엔드가
 * `{ error: <사유> }`를 실어 보낸다(`app/(chat)/api/approval/respond/route.ts`).
 * 이 경로에서는 resume 스트림에 도달하지 않으므로 그 fetch를 스텁할 필요가
 * 없다.
 */
function stubFetchWithRespondFailure(status: number, errorMessage: string) {
  globalThis.fetch = ((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.startsWith("/api/approval/respond")) {
      return Promise.resolve(
        new Response(JSON.stringify({ error: errorMessage }), { status })
      );
    }
    throw new Error(`이 테스트가 예상하지 못한 fetch: ${url}`);
  }) as typeof fetch;
}

function approvalMessage(): ChatMessage {
  return {
    id: "am1",
    role: "assistant",
    parts: [{ type: "text", text: "" }],
    metadata: {
      approval_session_id: "sess1",
      approval_requests: [
        { request_id: "r1", skill_name: "do_thing", params: {} },
      ],
    },
  } as ChatMessage;
}

/** approval 카드를 렌더하고 Approve를 눌러 비동기 체인이 끝나길 기다린다. */
async function renderAndApprove(message: ChatMessage): Promise<HTMLElement> {
  // 이 테스트는 setMessages/regenerate가 호출됐는지를 검사하지 않는다 --
  // approval 카드가 실제 fetch 결과로 무엇을 그리는지가 관심사다.
  const setMessages = (() => {
    /* no-op */
  }) as UseChatHelpers<ChatMessage>["setMessages"];
  const regenerate = (() => {
    /* no-op */
  }) as UseChatHelpers<ChatMessage>["regenerate"];

  const host = await renderComponent(
    <dataStreamModule.DataStreamProvider>
      <messageModule.PreviewMessage
        chatId="c1"
        isLoading={false}
        isReadonly={true}
        message={message}
        regenerate={regenerate}
        requiresScrollPadding={false}
        setMessages={setMessages}
        vote={undefined}
      />
    </dataStreamModule.DataStreamProvider>
  );

  const approveButton = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent?.trim().includes("Approve")
  );
  if (!approveButton) {
    throw new Error("Approve 버튼을 찾지 못했다");
  }

  await act(async () => {
    approveButton.click();
    // 순차 fetch(최대 두 번: respond → stream) + 스트림 읽기가 끝날 시간을 준다.
    await new Promise((resolve) => setTimeout(resolve, 10));
    await new Promise((resolve) => setTimeout(resolve, 10));
  });

  return host;
}

/**
 * 카드에서 백엔드 사유가 뜨는지, 정적 문구가 남아 있는지를 찾기만 한다 --
 * 단언은 각 test() 안에서 한다 (biome `noMisplacedAssertion`).
 */
function findBackendReasonSpans(host: HTMLElement, backendMessage: string) {
  const spans = Array.from(host.querySelectorAll("span"));
  return {
    reasonSpan: spans.find((span) =>
      span.textContent?.includes(backendMessage)
    ),
    staleGenericSpan: spans.find(
      (span) => span.textContent?.trim() === "Approval response failed"
    ),
  };
}

test("승인 실패 시 백엔드 메시지가 정적 문구 대신 화면에 뜬다 (resume 스트림 error)", async () => {
  const BACKEND_MESSAGE = "워크플로우 응답 대기 타임아웃";
  stubFetchWithStreamError(BACKEND_MESSAGE);

  const host = await renderAndApprove(approvalMessage());
  const { reasonSpan, staleGenericSpan } = findBackendReasonSpans(
    host,
    BACKEND_MESSAGE
  );

  assert.ok(
    reasonSpan,
    `백엔드 실패 사유("${BACKEND_MESSAGE}")가 화면에 없다 -- 정적 문구만 보인다면 회귀다`
  );
  assert.equal(
    staleGenericSpan,
    undefined,
    "정적 문구가 여전히 뜨고 있다 -- 백엔드 메시지로 대체돼야 한다"
  );
});

test("승인 요청 자체가 거부되면 그 사유가 화면에 뜬다 (POST /api/approval/respond 비정상 응답)", async () => {
  const BACKEND_MESSAGE = "세션이 이미 종결되었습니다";
  stubFetchWithRespondFailure(409, BACKEND_MESSAGE);

  const host = await renderAndApprove(approvalMessage());
  const { reasonSpan, staleGenericSpan } = findBackendReasonSpans(
    host,
    BACKEND_MESSAGE
  );

  assert.ok(
    reasonSpan,
    `백엔드 실패 사유("${BACKEND_MESSAGE}")가 화면에 없다 -- 정적 문구만 보인다면 회귀다`
  );
  assert.equal(
    staleGenericSpan,
    undefined,
    "정적 문구가 여전히 뜨고 있다 -- 백엔드 메시지로 대체돼야 한다"
  );
});
