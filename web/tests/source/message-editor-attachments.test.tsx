// DOM 전역을 **먼저** 세운다 -- `tests/dom-setup.ts` 상단 주석 참조.
import "../dom-setup";
import assert from "node:assert/strict";
import Module from "node:module";
import { before, beforeEach, test } from "node:test";
import type { UseChatHelpers } from "@ai-sdk/react";
import { act } from "react";
import type { ChatMessage } from "../../lib/types";
import { renderComponent } from "../render";

/**
 * 회귀 고정 (Task 3a): 메시지를 편집하면 file 파트가 사라진다.
 *
 * `message-editor.tsx`의 Send 핸들러가 `parts`를 텍스트 파트 하나로
 * 갈아치워 왔다 -- 첨부가 없던 시절엔 무해했지만, `convertBackendMessagesToUI`
 * (`lib/utils.ts`)가 새로고침 시 첨부를 file 파트로 복원하기 시작하면서
 * (b8094698) **도달 가능한** 손실이 됐다: 첨부 있는 메시지를 편집하면
 * 미리보기가 사라진다.
 *
 * 기대 동작: 편집은 텍스트만 바꾸고 file 파트는 보존한다. 순서는 텍스트가
 * 먼저, 첨부가 뒤 -- 복원 경로(`attachmentsToFileParts` 뒤에 이어붙이는
 * `convertBackendMessagesToUI`)가 만드는 순서와 같아야, 편집한 메시지와
 * 새로고침한 메시지가 같은 모양이 된다.
 */

/**
 * `message-editor.tsx`는 `@/app/(chat)/actions`의 `deleteTrailingMessages`
 * (서버 액션)를 임포트한다. 그 파일은 `next/headers`와 `@/app/(auth)/auth`를
 * 거쳐 `server-only`에 닿으므로, 클라이언트 번들링 마법이 없는 이
 * 테스트 러너(`tsx --test`, CJS 에밋)에서 그냥 임포트하면 죽는다.
 *
 * `approval-stream-proxy.test.ts`·`auth-login-expiry.test.ts`와 같은 기법:
 * 문제의 first-party 모듈 요청 하나만 스텁으로 가로채고 즉시 원상복구한다.
 */
let deleteTrailingMessagesCalls: unknown[] = [];

async function importMessageEditor() {
  const ModuleAny = Module as any;
  const originalLoad = ModuleAny._load;
  ModuleAny._load = (request: string, ...rest: any[]) => {
    if (request === "@/app/(chat)/actions") {
      return {
        deleteTrailingMessages: (args: unknown) => {
          deleteTrailingMessagesCalls.push(args);
        },
      };
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import("../../components/message-editor");
  } finally {
    ModuleAny._load = originalLoad;
  }
}

let MessageEditor: any;

before(async () => {
  ({ MessageEditor } = await importMessageEditor());
});

beforeEach(() => {
  deleteTrailingMessagesCalls = [];
});

/**
 * 컨트롤드 textarea에 값을 타이핑한다 (네이티브 setter로 React의 값 추적을
 * 우회). `dom-setup.ts`가 전역으로 옮기는 목록에 `HTMLTextAreaElement`가
 * 없으므로 프로토타입은 인스턴스에서 직접 걷어 올린다.
 */
function typeInto(textarea: HTMLTextAreaElement, value: string) {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    Object.getPrototypeOf(textarea),
    "value"
  )?.set;
  if (!nativeSetter) {
    throw new Error("textarea.value 네이티브 setter를 찾지 못했다");
  }
  nativeSetter.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

/**
 * 렌더 후 Send를 눌러 setMessages에 전달된 최종 메시지와 regenerate 호출
 * 여부를 회수한다. 이 함수 자체는 단언하지 않는다 -- 그건 호출부(각 test)
 * 몫이다.
 */
async function editAndSend(
  message: ChatMessage,
  draft: string
): Promise<{ updated: ChatMessage | undefined; regenerateCalled: boolean }> {
  let updated: ChatMessage | undefined;
  const initial = [message];
  const setMessages: UseChatHelpers<ChatMessage>["setMessages"] = ((
    updater: ChatMessage[] | ((messages: ChatMessage[]) => ChatMessage[])
  ) => {
    const next = typeof updater === "function" ? updater(initial) : updater;
    updated = next.find((m) => m.id === message.id);
  }) as UseChatHelpers<ChatMessage>["setMessages"];

  let regenerateCalled = false;
  const regenerate = (() => {
    regenerateCalled = true;
  }) as unknown as UseChatHelpers<ChatMessage>["regenerate"];

  const setMode = () => {
    // 뷰 모드 전환은 이 테스트의 관심사가 아니다.
  };

  const host = await renderComponent(
    <MessageEditor
      message={message}
      regenerate={regenerate}
      setMessages={setMessages}
      setMode={setMode}
    />
  );

  const textarea = host.querySelector(
    "[data-testid='message-editor']"
  ) as HTMLTextAreaElement | null;
  if (!textarea) {
    throw new Error("message-editor textarea를 찾지 못했다");
  }
  // `handleInput`이 `setDraftContent`(진짜 React state)를 부르므로 act 밖에서
  // 디스패치하면 "not wrapped in act" 경고가 뜬다.
  await act(() => {
    typeInto(textarea, draft);
  });

  const sendButton = host.querySelector(
    "[data-testid='message-editor-send-button']"
  ) as HTMLButtonElement | null;
  if (!sendButton) {
    throw new Error("send 버튼을 찾지 못했다");
  }

  await act(async () => {
    sendButton.click();
    // 클릭 핸들러는 `await deleteTrailingMessages(...)` 뒤에 setMessages를
    // 부른다 -- 마이크로태스크 큐가 비워질 시간을 준다.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  return { updated, regenerateCalled };
}

test("첨부 있는 메시지를 편집해도 file 파트가 살아남는다 (텍스트 먼저, 첨부 뒤)", async () => {
  const message: ChatMessage = {
    id: "m1",
    role: "user",
    parts: [
      { type: "text", text: "원본 텍스트" },
      {
        type: "file",
        url: "https://example.com/a.png",
        filename: "a.png",
        mediaType: "image/png",
      },
    ],
  } as ChatMessage;

  const { updated, regenerateCalled } = await editAndSend(
    message,
    "수정된 텍스트"
  );

  assert.equal(regenerateCalled, true, "regenerate가 호출되지 않았다");
  assert.ok(updated, "setMessages가 편집된 메시지를 넘기지 않았다");
  assert.equal(updated?.parts.length, 2, "file 파트가 사라졌다");
  assert.deepEqual(updated?.parts[0], {
    type: "text",
    text: "수정된 텍스트",
  });
  assert.deepEqual(updated?.parts[1], {
    type: "file",
    url: "https://example.com/a.png",
    filename: "a.png",
    mediaType: "image/png",
  });
});

test("첨부 없는 메시지의 기존 동작은 그대로다", async () => {
  const message: ChatMessage = {
    id: "m2",
    role: "user",
    parts: [{ type: "text", text: "원본" }],
  } as ChatMessage;

  const { updated, regenerateCalled } = await editAndSend(message, "새 텍스트");

  assert.equal(regenerateCalled, true, "regenerate가 호출되지 않았다");
  assert.ok(updated);
  assert.equal(updated?.parts.length, 1);
  assert.deepEqual(updated?.parts[0], { type: "text", text: "새 텍스트" });
});
