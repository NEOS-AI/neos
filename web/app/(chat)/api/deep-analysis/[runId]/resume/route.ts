/**
 * 실패한 deep_analysis run 재개 프록시 (POST 전용)
 *
 * 이벤트 프록시(`../events/route.ts`)는 GET 전용으로 남는다 -- 재접속이 재제출이
 * 되지 않게 하는 규율이다. 재개는 그것과 **다른 라우트**이고, 사람이 누른
 * 버튼만 부른다(`lib/deep-analysis/resume.ts`). 소유자 검사·재개 가능 상태
 * 판정(`running`/`failed`)·중복 지출 방지는 백엔드가 한다.
 */

import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  try {
    const { runId } = await params;
    const result = await callBackendAPIWithJSON(
      `/api/v1/deep-analysis/${encodeURIComponent(runId)}/resume`,
      { method: "POST" }
    );
    return NextResponse.json(result, { status: 202 });
  } catch (error: unknown) {
    return bffErrorResponse(error, "Could not resume deep analysis");
  }
}
