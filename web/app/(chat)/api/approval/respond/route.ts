import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const data = await callBackendAPIWithJSON("/api/v1/approval/respond", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(data);
  } catch (error: unknown) {
    return bffErrorResponse(error, "Approval response failed");
  }
}
