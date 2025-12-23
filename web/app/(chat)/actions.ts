"use server";

import { cookies } from "next/headers";
import type { VisibilityType } from "@/components/visibility-selector";
import {
  deleteMessagesByChatIdAfterTimestamp,
  getMessageById,
  updateChatVisibilityById,
} from "@/lib/db/queries";
import { callBackendAPI } from "@/lib/backend-api";

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
        body: JSON.stringify({
          user_message: userMessage,
        }),
      }
    );

    if (!response.ok) {
      console.error("Failed to generate title from backend");
      return "New chat";
    }

    const data = await response.json();
    return data.title || "New chat";
  } catch (error) {
    console.error("Error generating title:", error);
    return "New chat";
  }
}

export async function deleteTrailingMessages({ id }: { id: string }) {
  const [message] = await getMessageById({ id });

  await deleteMessagesByChatIdAfterTimestamp({
    chatId: message.chatId,
    timestamp: message.createdAt,
  });
}

export async function updateChatVisibility({
  chatId,
  visibility,
}: {
  chatId: string;
  visibility: VisibilityType;
}) {
  await updateChatVisibilityById({ chatId, visibility });
}
