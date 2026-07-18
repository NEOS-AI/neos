/**
 * deep_analysis 이벤트 스트림 리더 (DOM/React 비의존 — 테스트 가능)
 *
 * `ReadableStream<Uint8Array>` 하나를 소비하며 검증된 job 이벤트를 콜백으로
 * 흘린다. 훅(`hooks/use-deep-analysis-stream.ts`)은 재연결·백오프·상태만
 * 담당하고, 바이트 파싱은 전부 여기에 있다.
 *
 * 감사 §4.4가 지적한 "SSE 파서가 두 벌"을 세 벌로 늘리지 않으려 했으나,
 * 기존 두 파서 모두 이 계약을 못 읽는다: `lib/sse-stream.ts`는 `{event, data}`
 * 형식에 `parsed.event === "completed"`를 하드코딩했고 무검증 캐스팅을 한다
 * (§4.4), `use-chat-stream.ts`의 파서는 OpenResponses 챗 이벤트 전용이다.
 * 파서 단일화는 감사 §7 10행의 별도 과제이며, 여기서는 **검증되는** 리더를
 * 하나 더 두되 파싱 로직 자체는 `./events.ts`에 위임해 중복을 최소화했다.
 */

import { type DeepAnalysisJobEvent, parseJobEventLine } from "./events";

export type ReadEventStreamResult = {
  /** 스트림이 자연 종료(EOF)했다. 재연결 여부는 호출자가 정한다. */
  ended: true;
};

/**
 * SSE 본문을 끝까지 읽으며 이벤트를 `onEvent`로 넘긴다.
 *
 * - 검증에 실패한 라인은 조용히 버린다(keepalive 주석, `[DONE]`, 깨진 JSON).
 * - `onEvent`가 `false`를 반환하면 즉시 읽기를 멈춘다(종료 이벤트 수신 등).
 * - abort는 호출자가 `AbortController`로 fetch에 걸어 두고,
 *   여기서 발생하는 예외는 그대로 던진다 — 정지를 에러로 삼키지 않기 위해서다.
 */
export async function readDeepAnalysisEventStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: DeepAnalysisJobEvent) => boolean | undefined
): Promise<ReadEventStreamResult> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

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
        const event = parseJobEventLine(line);
        if (!event) {
          continue;
        }
        if (onEvent(event) === false) {
          return { ended: true };
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

  return { ended: true };
}
