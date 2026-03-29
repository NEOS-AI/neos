/**
 * Phase 8 (A2UI): UI 폼 제출 Route Handler
 *
 * 클라이언트 컴포넌트(UIFrameForm)에서 호출 → 백엔드 POST /api/v1/ui/submit 프록시.
 * auth()를 서버사이드에서 처리하여 backendAccessToken을 헤더에 주입한다.
 */

import { auth } from "@/app/(auth)/auth";
import { callBackendAPI } from "@/lib/backend-api";
import { ChatSDKError } from "@/lib/errors";

export async function POST(request: Request) {
  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:chat").toResponse();
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return new ChatSDKError("bad_request:api").toResponse();
  }

  const response = await callBackendAPI("/api/v1/ui/submit", {
    method: "POST",
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    return Response.json(data, { status: response.status });
  }

  // SSE 스트림 프록시 — 백엔드 스트림을 클라이언트로 그대로 전달
  return new Response(response.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
