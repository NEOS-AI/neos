import { auth, type UserType } from "@/app/(auth)/auth";
import type { VisibilityType } from "@/components/visibility-selector";
import { entitlementsByUserType } from "@/lib/ai/entitlements";
import type { ChatModel } from "@/lib/ai/models";
import { mapToBackendModelName } from "@/lib/ai/models";
import { callBackendAPI } from "@/lib/backend-api";
import {
  createStreamId,
  deleteChatById,
  getChatById,
  getMessageCountByUserId,
  saveChat,
  updateChatTitleById,
} from "@/lib/db/queries";
import { ChatSDKError } from "@/lib/errors";
import type { ChatMessage } from "@/lib/types";
import { generateUUID } from "@/lib/utils";
import { generateTitleFromUserMessage } from "../../actions";
import { type PostRequestBody, postRequestBodySchema } from "./schema";

export const maxDuration = 60;

export async function POST(request: Request) {
  let requestBody: PostRequestBody;

  try {
    const json = await request.json();
    requestBody = postRequestBodySchema.parse(json);
  } catch (_) {
    return new ChatSDKError("bad_request:api").toResponse();
  }

  try {
    const {
      id,
      message,
      selectedChatModel,
      selectedVisibilityType,
    }: {
      id: string;
      message: ChatMessage;
      selectedChatModel: ChatModel["id"];
      selectedVisibilityType: VisibilityType;
    } = requestBody;

    const session = await auth();

    if (!session?.user) {
      return new ChatSDKError("unauthorized:chat").toResponse();
    }

    const userType: UserType = session.user.type;

    const messageCount = await getMessageCountByUserId({
      id: session.user.id,
      differenceInHours: 24,
    });

    if (messageCount > entitlementsByUserType[userType].maxMessagesPerDay) {
      return new ChatSDKError("rate_limit:chat").toResponse();
    }

    const chat = await getChatById({ id });
    let titlePromise: Promise<string> | null = null;
    let conversationId: string | null = null;

    // Extract message content early for title generation
    const messageContent = message.parts
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n");

    if (chat) {
      if (chat.userId !== session.user.id) {
        return new ChatSDKError("forbidden:chat").toResponse();
      }
      conversationId = id;
    } else {
      // Save chat immediately with placeholder title
      await saveChat({
        id,
        userId: session.user.id,
        title: "New chat",
        visibility: selectedVisibilityType,
      });

      // Create conversation in backend
      try {
        const createConversationResponse = await callBackendAPI(
          "/api/v1/chat/conversations",
          {
            method: "POST",
            body: JSON.stringify({
              user_id: session.user.backendUserId || session.user.id,
              title: "New chat",
              model_name: mapToBackendModelName(selectedChatModel),
              mode: "standard",
              temperature: 0.7,
            }),
          }
        );

        if (!createConversationResponse.ok) {
          throw new Error("Failed to create conversation in backend");
        }

        const conversationData = await createConversationResponse.json();
        conversationId = conversationData.conversation_id || id;

        // Start title generation in parallel (non-blocking)
        if (conversationId) {
          titlePromise = generateTitleFromUserMessage({
            conversationId,
            userMessage: messageContent,
          });
        }
      } catch (error) {
        console.error("Failed to create backend conversation:", error);
        // Use the local chat ID as fallback
        conversationId = id;
      }
    }

    // Handle title generation in parallel
    if (titlePromise) {
      titlePromise.then((title: string) => {
        console.log("Generated title:", title);
        updateChatTitleById({ chatId: id, title });
      }).catch((error) => {
        console.error("Failed to update title:", error);
      });
    }

    const streamId = generateUUID();
    await createStreamId({ streamId, chatId: id });

    // Call backend streaming API
    const backendStreamResponse = await callBackendAPI(
      `/api/v1/chat/conversations/${conversationId}/messages/stream`,
      {
        method: "POST",
        body: JSON.stringify({
          content: messageContent,
          role: "user",
          metadata: {
            chat_id: id,
            model: selectedChatModel,
            visibility: selectedVisibilityType,
          },
        }),
      }
    );

    if (!backendStreamResponse.ok) {
      const errorText = await backendStreamResponse.text();
      console.error("Backend streaming error:", errorText);
      return new ChatSDKError("offline:chat").toResponse();
    }

    // Proxy backend SSE directly (no transformation)
    // This preserves the JSON structure and event-stream format
    return new Response(backendStreamResponse.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error) {
    const vercelId = request.headers.get("x-vercel-id");

    if (error instanceof ChatSDKError) {
      return error.toResponse();
    }

    console.error("Unhandled error in chat API:", error, { vercelId });
    return new ChatSDKError("offline:chat").toResponse();
  }
}

export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");

  if (!id) {
    return new ChatSDKError("bad_request:api").toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:chat").toResponse();
  }

  const chat = await getChatById({ id });

  if (chat?.userId !== session.user.id) {
    return new ChatSDKError("forbidden:chat").toResponse();
  }

  const deletedChat = await deleteChatById({ id });

  return Response.json(deletedChat, { status: 200 });
}
