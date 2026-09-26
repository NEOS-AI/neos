import { NextResponse } from "next/server";
import { callBackendAPI } from "@/lib/backend-api";

type Context = { params: Promise<{ model: string[] }> };

async function forward(
  method: "PUT" | "DELETE",
  params: Context["params"],
  body?: string
) {
  const { model } = await params;
  const path = model.map(encodeURIComponent).join("/");
  try {
    const response = await callBackendAPI(
      `/api/v1/users/me/model-preferences/${path}`,
      { method, body }
    );
    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    return NextResponse.json(await response.json(), {
      status: response.status,
    });
  } catch {
    return NextResponse.json({ error: "Update failed" }, { status: 502 });
  }
}

export async function PUT(request: Request, { params }: Context) {
  return forward("PUT", params, await request.text());
}

export function DELETE(_request: Request, { params }: Context) {
  return forward("DELETE", params);
}
