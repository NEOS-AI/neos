import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";

/**
 * 슬래시 커맨드 카탈로그. 입력기가 `/word` 를 커맨드로 보낼지 steer 로 넘길지를
 * 이 목록으로 정한다(`features/coding/commands/route-input.ts`).
 */
export async function GET() {
  try {
    const catalog = await callBackendAPIWithJSON("/api/v1/coding/commands");
    return NextResponse.json(catalog);
  } catch (error: unknown) {
    return bffErrorResponse(error, "Could not load coding commands");
  }
}
