import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";

/**
 * 샌드박스 상태 프록시. **GET 만 둔다.**
 *
 * POST 를 두면 브라우저에서 할당을 다시 만들 수 있는 경로가 생긴다 --
 * deep-analysis 프록시가 재과금 사고(`autoResume` 가 재개가 아니라 재실행
 * 이었다) 뒤에 세운 규율과 같은 이유다. 이 라우트는 읽기만 한다.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await context.params;
    const status = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/sandbox-status`
    );
    return NextResponse.json(status);
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Could not read sandbox status" },
      { status: cause.status ?? 500 }
    );
  }
}
