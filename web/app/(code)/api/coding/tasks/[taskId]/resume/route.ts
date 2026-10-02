import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";

// 트랙 Q10b -- 멈춘(paused) 태스크를 사람이 재개한다. 백엔드는 standing_agents 가
// 켜졌을 때만 이 라우트를 마운트하고, 멈추지 않은 태스크에는 409 task_not_paused 다.
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await params;
    const result = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/resume`,
      { method: "POST" }
    );
    return NextResponse.json(result, { status: 202 });
  } catch (error: unknown) {
    return bffErrorResponse(error, "Could not resume coding task");
  }
}
