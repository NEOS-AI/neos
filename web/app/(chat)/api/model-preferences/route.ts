import { NextResponse } from "next/server";
import { callBackendAPI } from "@/lib/backend-api";

// 선호를 못 읽으면 빈 목록 — 모든 모델이 기본값으로 보일 뿐 채팅은 영향 없다.
export async function GET() {
  try {
    const response = await callBackendAPI("/api/v1/users/me/model-preferences");
    if (!response.ok) {
      return NextResponse.json([]);
    }
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json([]);
  }
}
