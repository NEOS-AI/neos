import { NextResponse } from "next/server";
import { callBackendAPIWithJSON } from "@/lib/backend-api";


export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = searchParams.get("limit");
    const query = new URLSearchParams();
    if (limit !== null) {
      query.set("limit", limit);
    }
    const encoded = query.toString();
    const suffix = encoded ? `?${encoded}` : "";
    const tasks = await callBackendAPIWithJSON(
      `/api/v1/coding/tasks${suffix}`
    );
    return NextResponse.json(tasks);
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Could not load coding tasks" },
      { status: cause.status ?? 500 }
    );
  }
}


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
