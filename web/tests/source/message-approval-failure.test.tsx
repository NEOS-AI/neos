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
 * 회귀 고정 (Task 3b): 승인 실패 메시지가 화면에 도달하지 않는다.
 *
 * `respondToApproval`의 catch가 `error.message`를 버리고 정적 문구
 * "Approval response failed"만 보여줬다. resume 스트림이 종결
 * `error` 이벤트로 끝나면(예: 백엔드의 "워크플로우 응답 대기 타임아웃")
 * 그 이유가 카드에 그대로 보여야 한다.
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

test("승인 실패 시 백엔드 메시지가 정적 문구 대신 화면에 뜬다", async () => {
  const BACKEND_MESSAGE = "워크플로우 응답 대기 타임아웃";
  stubFetchWithStreamError(BACKEND_MESSAGE);

  const message: ChatMessage = {
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
  assert.ok(approveButton, "Approve 버튼을 찾지 못했다");

  await act(async () => {
    approveButton?.click();
    // 순차 fetch 두 번(respond → stream) + 스트림 읽기가 끝날 시간을 준다.
    await new Promise((resolve) => setTimeout(resolve, 10));
    await new Promise((resolve) => setTimeout(resolve, 10));
  });

  const errorSpan = Array.from(host.querySelectorAll("span")).find((span) =>
    span.textContent?.includes(BACKEND_MESSAGE)
  );
  assert.ok(
    errorSpan,
    `백엔드 실패 사유("${BACKEND_MESSAGE}")가 화면에 없다 -- 정적 문구만 보인다면 회귀다`
  );

  const staleGeneric = Array.from(host.querySelectorAll("span")).find(
    (span) => span.textContent?.trim() === "Approval response failed"
  );
  assert.equal(
    staleGeneric,
    undefined,
    "정적 문구가 여전히 뜨고 있다 -- 백엔드 메시지로 대체돼야 한다"
  );
});
