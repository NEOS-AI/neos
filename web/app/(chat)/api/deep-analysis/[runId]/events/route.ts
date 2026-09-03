/**
 * deep_analysis job 이벤트 스트림 프록시 (GET 전용)
 *
 * `app/(chat)/api/approval/stream/[sessionId]/route.ts`와 같은 패턴이다:
 * 브라우저는 백엔드 토큰을 갖고 있지 않으므로 `callBackendAPI`를 거쳐야 한다.
 * run 소유자 검사는 백엔드가 한다(소유자가 아니면 404).
 *
 * ⚠️ **이 라우트에는 POST가 없다.** 재접속은 커서를 든 GET일 뿐이며,
 * job 재제출 경로를 프론트에 두지 않는 것이 감사 §4.2 재과금 사고의
 * 재발 방지책이다.
 */

import { callBackendAPI } from "@/lib/backend-api";

// SSE는 정적 최적화 대상이 아니다 — 다만 그것을 `export const dynamic` 으로
// 말하지 않는다. `next.config.ts` 가 `cacheComponents: true` 라 그 세그먼트
// 설정 자체가 금지돼 있고(빌드가 "not compatible with nextConfig.cacheComponents"
// 로 거부한다), **저장소 전체에서 이 파일 하나만 그것을 쓰고 있었다.**
//
// 필요도 없다. 이 핸들러는 `request.url` 을 읽고 `request.signal` 을 넘기므로
// 요청 시점 API 를 쓰는 것이 곧 동적이라는 뜻이다 — cacheComponents 모드에서
// 동적 여부는 선언이 아니라 **무엇을 읽는가**로 정해진다.

/**
 * 기본 상한(60초)은 장시간 job 스트림과 충돌한다(감사 §6-3). 상한을 올리되,
 * 어차피 끊길 수 있다는 전제로 클라이언트가 커서를 들고 재구독한다
 * (`hooks/use-deep-analysis-stream.ts`). 끊김은 손실이 아니다.
 *
 * ⚠️ 원문은 "챗 라우트의 `maxDuration = 60`"이라 적었다. 챗 라우트도
 * 2026-08-25 에 300 으로 올라갔으므로(TODO #14) 그 대비는 더 이상 참이 아니다.
 */
export const maxDuration = 300;

const MAX_CURSOR = Number.MAX_SAFE_INTEGER;

function parseAfter(value: string | null): number {
  if (!value) {
    return 0;
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > MAX_CURSOR) {
    return 0;
  }
  return parsed;
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  const { runId } = await params;
  const after = parseAfter(new URL(request.url).searchParams.get("after"));

  const backendResponse = await callBackendAPI(
    `/api/v1/deep-analysis/${encodeURIComponent(runId)}/events?after=${after}`,
    { signal: request.signal }
  );

  if (!(backendResponse.ok && backendResponse.body)) {
    return new Response(await backendResponse.text(), {
      status: backendResponse.ok ? 502 : backendResponse.status,
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
