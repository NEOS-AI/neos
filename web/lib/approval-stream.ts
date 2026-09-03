/**
 * approval resume SSE 스트림 리더 (DOM/React 비의존 -- 테스트 가능)
 *
 * `POST /api/approval/respond` 이후 클라이언트가 재구독하는
 * `GET /api/approval/stream/{sessionId}`의 응답 본문을 소비한다.
 *
 * 백엔드 정상 경로는 `StreamEvent.to_sse_format()`을 써서 `event:` 줄을
 * 붙이지만(`neos/workflow/stream_manager.py:30`), 과거 타임아웃 경로는
 * `data:` 한 줄만 손으로 내보내면서 payload 안에 `event` 키를 중복으로
 * 넣어 뒀다. 그 습관이 남아 있을 수 있고, 저장소의 다른 파서
 * (`./sse-stream.ts`의 `readSseStream`)도 `parsed.event` 필드로 종류를
 * 판별하는 관례를 쓰므로, 이 리더는 **둘 다** 받는다: `event:` 줄이
 * 있으면 그것을 쓰고, 없으면 payload의 `event` 필드로 대체한다.
 *
 * 감사 finding #3의 직접 원인은 이전 구현(컴포넌트 내부의
 * `readApprovalResumeStream`)이 `eventName`을 이벤트 경계(빈 줄)에서
 * 초기화하지 않아, 타임아웃 payload가 직전 `node_complete`로 오판되고
 * completed/error 어느 분기도 타지 않은 채 스트림이 조용히 끝나
 * 호출부가 "완료"로 찍은 것이다. 여기서는 빈 줄마다 `eventName`을
 * 리셋하고, 종결 이벤트(`completed`/`error`) 없이 스트림이 끝나면
 * 그것을 성공과 구분되는 결과(`{ status: "ended" }`)로 돌려준다.
 */

export type ApprovalStreamOutcome =
  | { status: "completed"; text: string }
  | { status: "error"; message: string }
  /** 종결 이벤트 없이 스트림이 끝났다 -- 성공으로 취급하면 안 된다. */
  | { status: "ended" };

function extractText(payload: Record<string, unknown>): string {
  if (typeof payload.response === "string") {
    return payload.response;
  }
  const nested = payload.data as Record<string, unknown> | undefined;
  if (nested && typeof nested.response === "string") {
    return nested.response;
  }
  return "";
}

function extractMessage(payload: Record<string, unknown>): string {
  if (typeof payload.message === "string") {
    return payload.message;
  }
  const nested = payload.data as Record<string, unknown> | undefined;
  if (nested && typeof nested.message === "string") {
    return nested.message;
  }
  return "Approval resume failed";
}

/**
 * approval resume 스트림 본문을 끝까지 읽고 최종 결과를 반환한다.
 *
 * - 이벤트 종류는 `event:` 줄, 없으면 payload의 `event` 필드로 판별한다.
 * - 빈 줄(이벤트 경계)마다 `eventName`을 초기화한다.
 * - `data:` 줄의 JSON 파싱에 실패하면 그 줄만 건너뛴다.
 */
export async function readApprovalResumeStream(
  stream: ReadableStream<Uint8Array>
): Promise<ApprovalStreamOutcome> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line === "") {
          // SSE 이벤트 경계 -- 다음 이벤트로 새지 않도록 리셋한다.
          eventName = "";
          continue;
        }
        if (line.startsWith("event:")) {
          eventName = line.slice("event:".length).trim();
          continue;
        }
        if (!line.startsWith("data:")) {
          continue;
        }

        const payloadText = line.slice("data:".length).trim();
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(payloadText) as Record<string, unknown>;
        } catch {
          // 깨진 JSON(예: keepalive 주석 취급된 줄)은 이 줄만 버린다.
          continue;
        }

        const kind = eventName || (payload.event as string | undefined) || "";

        if (kind === "completed") {
          return { status: "completed", text: extractText(payload) };
        }
        if (kind === "error") {
          return { status: "error", message: extractMessage(payload) };
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // 이미 해제된 경우 무시
    }
  }

  return { status: "ended" };
}
