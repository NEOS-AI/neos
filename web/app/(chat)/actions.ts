"use server";

import { cookies } from "next/headers";
import { auth } from "@/app/(auth)/auth";
import { callBackendAPI } from "@/lib/backend-api";
import type { VisibilityType } from "@/components/visibility-selector";

export async function saveChatModelAsCookie(model: string) {
  const cookieStore = await cookies();
  cookieStore.set("chat-model", model);
}

export async function generateTitleFromUserMessage({
  conversationId,
  userMessage,
}: {
  conversationId: string;
  userMessage: string;
}) {
  try {
    const response = await callBackendAPI(
      `/api/v1/chat/conversations/${conversationId}/generate-title`,
      {
        method: "POST",
        body: JSON.stringify({ user_message: userMessage }),
      }
    );

    if (!response.ok) return "New chat";
    const data = await response.json();
    return data.title || "New chat";
  } catch {
    return "New chat";
  }
}

export async function deleteTrailingMessages({ id }: { id: string }) {
  const session = await auth();
  if (!session?.user) return;

  // id는 FE message UUID가 아니라 BE message_id로 전달됨
  // 해당 메시지의 created_at을 조회한 후 그 이후 메시지를 삭제
  const msgRes = await callBackendAPI(`/api/v1/chat/messages/${id}`);
  if (!msgRes.ok) return;

  const msg = await msgRes.json();
  const conversationId = msg.conversation_id;
  const timestamp: string = msg.created_at;

  await callBackendAPI(
    `/api/v1/chat/conversations/${conversationId}/messages/after?timestamp=${encodeURIComponent(timestamp)}`,
    { method: "DELETE" }
  );
}

export async function updateChatVisibility({
  chatId,
  visibility,
}: {
  chatId: string;
  visibility: VisibilityType;
}) {
  // chatId = backendConversationId (Phase 3 이후 FE는 conversation_id를 사용)
  await callBackendAPI(`/api/v1/chat/conversations/${chatId}`, {
    method: "PATCH",
    body: JSON.stringify({ visibility }),
  });
}
