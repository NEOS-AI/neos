import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await params;
    const result = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/steer`,
      { method: "POST", body: JSON.stringify(await request.json()) }
    );
    return NextResponse.json(result, { status: 202 });
  } catch (error: unknown) {
    return bffErrorResponse(error, "Could not steer coding task");
  }
}
