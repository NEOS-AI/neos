/**
 * A2UI 폼 제출 — **클라이언트에서 부르는** 유일한 백엔드 헬퍼
 *
 * ## 왜 `backend-api.ts` 에서 나왔나
 *
 * 이 함수는 처음부터 클라이언트용이었다(원 독스트링: "클라이언트 컴포넌트에서
 * 직접 호출 가능"). 그런데 `lib/backend-api.ts` 안에 살고 있었고, 그 모듈은
 * 최상위에서 `auth()` 와 `lib/server-config`(= `import "server-only"`)를
 * 끌어온다. **모듈에서 무엇을 가져오든 모듈 전체가 번들에 들어가므로**,
 * 클라이언트 컴포넌트가 이 함수 하나를 임포트하는 것만으로 `server-only` 가
 * 클라이언트 번들에 들어가 빌드가 깨졌다.
 *
 * 즉 선언된 의도(주석)와 실제 경계(모듈)가 어긋나 있었고, 주석은 번들러에게
 * 아무 말도 하지 않는다. 파일을 나누는 것이 그 의도를 **코드로** 적는 방법이다.
 *
 * ⚠️ **이 파일에는 서버 전용 임포트를 두지 말 것.** `auth`, `lib/server-config`,
 * `next/headers`, `server-only` 중 하나라도 들어오면 이 모듈을 임포트하는
 * 클라이언트 컴포넌트가 다시 빌드를 깬다 — 나눈 이유가 사라진다.
 * 서버에서 백엔드를 부르는 것은 전부 `lib/backend-api.ts` 다.
 */

/**
 * UI 폼을 제출한다. 백엔드를 직접 부르지 않는다 — 인증 토큰이 필요하므로
 * Next 라우트 핸들러(`/api/ui-submit`)를 경유하고, 그쪽이 세션을 붙인다.
 *
 * @returns SSE 스트림을 담은 `Response`. 호출자가 직접 읽는다.
 */
export async function submitUIFrameClient(
  frameId: string,
  sessionId: string,
  values: Record<string, unknown>,
  conversationId?: string
): Promise<Response> {
  const response = await fetch("/api/ui-submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      frame_id: frameId,
      session_id: sessionId,
      values,
      conversation_id: conversationId,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(
      err.detail || err.message || `UI submit failed (${response.status})`
    );
  }

  return response;
}
