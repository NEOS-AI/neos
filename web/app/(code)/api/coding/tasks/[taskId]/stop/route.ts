import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await params;
    const result = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/stop`,
      { method: "POST" }
    );
    return NextResponse.json(result, { status: 202 });
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Could not stop coding task" },
      { status: cause.status ?? 500 }
    );
  }
}
