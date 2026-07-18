import type { NextRequest } from "next/server";
import { auth } from "@/app/(auth)/auth";
import { adaptBEConversationList } from "@/lib/adapters/chat-adapters";
import { callBackendAPI } from "@/lib/backend-api";
import { ChatSDKError } from "@/lib/errors";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const limit = Number.parseInt(searchParams.get("limit") || "10", 10);
  const cursor = searchParams.get("cursor");

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:chat").toResponse();
  }

  const userId = session.user.backendUserId || session.user.id;
  const query = cursor
    ? `limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `limit=${limit}`;
  const res = await callBackendAPI(
    `/api/v1/chat/users/${userId}/conversations?${query}`
  );

  if (!res.ok) {
    return new ChatSDKError("bad_request:database").toResponse();
  }

  const raw = await res.json();
  return Response.json(adaptBEConversationList(raw));
}

export async function DELETE() {
  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:chat").toResponse();
  }

  const userId = session.user.backendUserId || session.user.id;
  const res = await callBackendAPI(
    `/api/v1/chat/users/${userId}/conversations`,
    { method: "DELETE" }
  );

  if (!res.ok) {
    return new ChatSDKError("bad_request:database").toResponse();
  }

  const result = await res.json();
  return Response.json(result, { status: 200 });
}
