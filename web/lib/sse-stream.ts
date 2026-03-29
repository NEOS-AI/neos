/**
 * SSE 스트림 파서 유틸리티
 *
 * UIFrameForm, 향후 ApprovalStream 등 SSE를 소비하는 컴포넌트에서 재사용.
 * NEOS 백엔드의 `data: {"event": "...", "data": {...}}` 형식을 파싱한다.
 */

export interface SseEvent {
  event?: string;
  data?: unknown;
}

/**
 * ReadableStream을 소비하여 'completed' 이벤트의 응답 텍스트를 반환한다.
 *
 * @param stream  - Response.body (ReadableStream<Uint8Array>)
 * @param onEvent - 각 이벤트에 대한 선택적 콜백 (실시간 처리 필요 시)
 * @returns 'completed' 이벤트의 data.response 값 또는 null
 */
export async function readSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent?: (event: SseEvent) => void
): Promise<string | null> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: string | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
        try {
          const parsed = JSON.parse(line.slice(6)) as SseEvent;
          onEvent?.(parsed);
          const eventData = parsed.data as Record<string, unknown> | undefined;
          if (parsed.event === "completed" && eventData?.response) {
            result = eventData.response as string;
          }
        } catch {
          // 파싱 오류 무시 (불완전한 청크 등)
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  return result;
}
