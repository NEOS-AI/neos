import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";

export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await context.params;
    const snapshot = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/snapshot`
    );
    return NextResponse.json(snapshot);
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Could not restore coding task" },
      { status: cause.status ?? 500 }
    );
  }
}
