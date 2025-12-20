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
// import { generateTitleFromUserMessage } from "../../actions"; // TODO: Re-enable when backend supports title generation
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

      // TODO: Start title generation in parallel (currently disabled - uses Vercel AI Gateway)
      // titlePromise = generateTitleFromUserMessage({ message });

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
      } catch (error) {
        console.error("Failed to create backend conversation:", error);
        // Use the local chat ID as fallback
        conversationId = id;
      }
    }

    // Handle title generation in parallel
    if (titlePromise) {
      titlePromise.then((title: string) => {
        updateChatTitleById({ chatId: id, title });
      });
    }

    const streamId = generateUUID();
    await createStreamId({ streamId, chatId: id });

    // Extract message content
    const messageContent = message.parts
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n");

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

    // Transform backend SSE to Vercel AI SDK format with line buffering
    let buffer = "";
    const transformedStream = backendStreamResponse.body!
      .pipeThrough(new TextDecoderStream())
      .pipeThrough(
        new TransformStream<string, string>({
          async transform(chunk: string, controller: TransformStreamDefaultController<string>) {
            // Append chunk to buffer
            buffer += chunk;
            const lines = buffer.split("\n");

            // Keep the last incomplete line in the buffer
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (!line.trim() || !line.startsWith("data: ")) continue;

              try {
                const jsonData = JSON.parse(line.substring(6));

                // Transform backend SSE format to Vercel AI SDK format
                if (jsonData.type === "start") {
                  // Start event - send message ID as metadata
                  controller.enqueue(
                    `2:${JSON.stringify([
                      {
                        type: "message_start",
                        data: { id: jsonData.message_id },
                      },
                    ])}\n`
                  );
                } else if (jsonData.type === "content") {
                  // Content event - send as text delta
                  if (jsonData.content) {
                    controller.enqueue(`0:${JSON.stringify(jsonData.content)}\n`);
                  }
                } else if (jsonData.type === "complete") {
                  // Complete event - send finish reason and metadata
                  const finishData: Record<string, any> = {
                    finishReason: "stop",
                  };

                  if (jsonData.metadata) {
                    finishData.usage = {
                      promptTokens: jsonData.metadata.prompt_tokens || 0,
                      completionTokens: jsonData.metadata.completion_tokens || 0,
                      totalTokens: jsonData.metadata.total_tokens || 0,
                    };
                  }

                  controller.enqueue(`d:${JSON.stringify(finishData)}\n`);
                } else if (jsonData.type === "error") {
                  // Error event
                  controller.enqueue(
                    `3:${JSON.stringify({ error: jsonData.error })}\n`
                  );
                }
              } catch (e) {
                console.error("Failed to parse SSE chunk:", line, e);
              }
            }
          },
          flush(controller: TransformStreamDefaultController<string>) {
            // Process any remaining data in buffer
            if (buffer.trim() && buffer.startsWith("data: ")) {
              try {
                const jsonData = JSON.parse(buffer.substring(6));
                if (jsonData.type === "complete") {
                  const finishData: Record<string, any> = {
                    finishReason: "stop",
                  };
                  if (jsonData.metadata) {
                    finishData.usage = {
                      promptTokens: jsonData.metadata.prompt_tokens || 0,
                      completionTokens: jsonData.metadata.completion_tokens || 0,
                      totalTokens: jsonData.metadata.total_tokens || 0,
                    };
                  }
                  controller.enqueue(`d:${JSON.stringify(finishData)}\n`);
                }
              } catch (e) {
                console.error("Failed to parse remaining buffer:", buffer, e);
              }
            }
          },
        })
      )
      .pipeThrough(new TextEncoderStream());

    return new Response(transformedStream, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Vercel-AI-Data-Stream": "v1",
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
