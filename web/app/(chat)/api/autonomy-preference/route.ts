import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";

export async function GET() {
  try {
    const data = await callBackendAPIWithJSON("/api/v1/autonomy/preference");
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ autonomy_level: null, source: "fallback" });
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json();
    const data = await callBackendAPIWithJSON("/api/v1/autonomy/preference", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Update failed" }, { status: 500 });
  }
}
