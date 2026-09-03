import { callBackendAPI } from "@/lib/backend-api";

/**
 * 이 스트림의 실제 상한은 BE가 세션 큐를 자동 종료하는 60초다
 * (`neos/api/handlers/approval_handlers.py:307`, `asyncio.wait_for(timeout=60.0)`).
 * 형제 라우트(`deep-analysis/[runId]/events/route.ts`)의 300초는 장시간
 * job 스트림 상한이라 여기 근거가 아니다 — BE가 어차피 60초에 끊으므로
 * 그보다 넉넉한 여유만 있으면 된다. 90초(60초 + 50% 여유)로 둔다.
 *
 * ⚠️ `export const dynamic`은 쓰지 않는다. `next.config.ts`가
 * `cacheComponents: true`라 그 세그먼트 옵션 자체가 빌드 오류이고
 * (형제 라우트 주석 참조), 이 핸들러는 `request.signal`을 읽으므로
 * 요청 시점 API 사용 자체로 이미 동적이다.
 */
export const maxDuration = 90;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;
  const backendResponse = await callBackendAPI(
    `/api/v1/approval/stream/${encodeURIComponent(sessionId)}`,
    { signal: request.signal }
  );

  if (!backendResponse.ok) {
    return new Response(await backendResponse.text(), {
      status: backendResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(backendResponse.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
