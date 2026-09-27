import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";
import { getCodingWsPublicUrl } from "@/lib/server-config";


export async function POST(
  _request: Request,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await params;
    const result = await callBackendAPIWithJSON<{ ticket: string; expires_in: number }>(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/ws-ticket`,
      { method: "POST" }
    );
    return NextResponse.json({
      ...result,
      websocket_url: `${getCodingWsPublicUrl()}/api/v1/coding/ws`,
    });
  } catch (error: unknown) {
    return bffErrorResponse(error, "Could not authorize coding stream");
  }
}
