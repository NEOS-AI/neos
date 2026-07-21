import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";

export async function POST(
  request: Request,
  {
    params,
  }: { params: Promise<{ taskId: string; approvalId: string }> }
) {
  try {
    const { taskId, approvalId } = await params;
    const result = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approvalId)}`,
      { method: "POST", body: JSON.stringify(await request.json()) }
    );
    return NextResponse.json(result);
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Could not resolve coding approval" },
      { status: cause.status ?? 500 }
    );
  }
}
