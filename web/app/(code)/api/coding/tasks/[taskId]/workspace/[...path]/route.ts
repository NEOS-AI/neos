import { NextResponse } from "next/server";
import { callBackendAPI } from "@/lib/backend-api";
import { getCodingWsPublicUrl } from "@/lib/server-config";

const ALLOWED_OPERATIONS = new Map([
  ["GET:tree", "tree"],
  ["GET:files", "files"],
  ["GET:diff", "diff"],
  ["PUT:files", "files"],
  ["POST:ws-ticket", "ws-ticket"],
]);

type Context = {
  params: Promise<{ taskId: string; path: string[] }>;
};

async function proxy(request: Request, context: Context) {
  const { taskId, path } = await context.params;
  const operation = path.join("/");
  const allowed = ALLOWED_OPERATIONS.get(`${request.method}:${operation}`);
  if (!allowed) {
    return NextResponse.json(
      { error: "Unsupported workspace operation" },
      { status: 404 }
    );
  }
  const incoming = new URL(request.url);
  const backendPath =
    `/api/v1/coding/tasks/${encodeURIComponent(taskId)}/workspace/${allowed}` +
    incoming.search;
  try {
    const response = await callBackendAPI(backendPath, {
      method: request.method,
      body: request.method === "PUT" ? await request.text() : undefined,
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok && allowed === "ws-ticket") {
      const suffix =
        incoming.searchParams.get("kind") === "pty" ? "pty/ws" : "workspace/ws";
      body.websocket_url = `${getCodingWsPublicUrl()}/api/v1/coding/${suffix}`;
    }
    return NextResponse.json(body, { status: response.status });
  } catch (error: unknown) {
    const cause = error as { message?: string; status?: number };
    return NextResponse.json(
      { error: cause.message ?? "Workspace request failed" },
      { status: cause.status ?? 500 }
    );
  }
}

export const GET = proxy;
export const PUT = proxy;
export const POST = proxy;
