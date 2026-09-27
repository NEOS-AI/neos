import { NextResponse } from "next/server";

/**
 * BFF 라우트의 catch 블록 하나.
 *
 * `callBackendAPIWithJSON` 이 던진 `BackendAPIError` 는 이미 읽을 수 있는
 * message 와 백엔드 `code` 를 들고 있다(`lib/backend-error.ts`). 여기서는
 * 그것을 `{error, code}` + 원래 status 로 옮기기만 한다. 백엔드에서 온 오류가
 * 아니면(네트워크 실패 등) 내부 문구를 흘리지 않고 fallback 으로 500 을 낸다.
 *
 * 브라우저 쪽은 `backendErrorMessage()` 가 `error` 키를 읽는다.
 */
export function bffErrorResponse(error: unknown, fallback: string): NextResponse {
  const cause = error as { message?: unknown; status?: unknown; code?: unknown };
  const status = typeof cause?.status === "number" ? cause.status : null;
  if (status === null) {
    return NextResponse.json({ error: fallback }, { status: 500 });
  }
  const message =
    typeof cause.message === "string" && cause.message ? cause.message : fallback;
  const code = typeof cause.code === "string" && cause.code ? cause.code : undefined;
  return NextResponse.json(code ? { error: message, code } : { error: message }, {
    status,
  });
}
