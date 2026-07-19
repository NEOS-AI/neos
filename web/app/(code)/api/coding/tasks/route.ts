import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";


export async function POST(request: Request) {
  try {
    const body = await request.json();
    const task = await callBackendAPIWithJSON("/api/v1/coding/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(task, { status: 202 });
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Could not start coding task" },
      { status: cause.status ?? 500 }
    );
  }
}
