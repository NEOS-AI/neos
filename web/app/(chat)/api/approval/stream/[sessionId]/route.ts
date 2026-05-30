import { callBackendAPI } from "@/lib/backend-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;
  const backendResponse = await callBackendAPI(
    `/api/v1/approval/stream/${encodeURIComponent(sessionId)}`
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
