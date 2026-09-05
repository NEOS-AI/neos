import { auth, type UserType } from "@/app/(auth)/auth";
import { adaptBEConversation } from "@/lib/adapters/chat-adapters";
import { entitlementsByUserType } from "@/lib/ai/entitlements";
import { mapToBackendModelName } from "@/lib/ai/models";
import { callBackendAPI } from "@/lib/backend-api";
import { ChatSDKError } from "@/lib/errors";
import { extractAttachments, extractTextContent } from "@/lib/message-parts";
import { isAbortError } from "@/lib/stream-errors";
import { generateTitleFromUserMessage } from "../../actions";
import { type PostRequestBody, postRequestBodySchema } from "./schema";

// 이 라우트는 백엔드의 `/messages/stream` 을 프록시한다(아래 POST 참고) --
// 요청 하나가 모델이 답을 다 쓸 때까지 열려 있는다. 60초는 그보다 짧아서 긴
// 답변이 중간에 끊겼다.
//
// 300은 `app/(chat)/api/deep-analysis/[runId]/events/route.ts` 와 같은 값이다.
// 둘은 같은 종류의 것 -- 오래 열려 있는 SSE 프록시 -- 이므로 값을 따로 두면
// 한쪽만 고쳐질 때 왜 다른지 아무도 설명하지 못하게 된다.
//
// ⚠️ 심층분석이 여기서 도는 것은 **아니다.** D23 이후 챗 노드는 job 을 제출만
// 하므로(`graph.py:1051-1122`) 그쪽 시간은 이 상한과 무관하다. 이 값이 지키는
// 것은 일반 챗 스트림이다.
export const maxDuration = 300;

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
      autonomy_level: autonomyLevel,
    } = requestBody;

    const session = await auth();

    if (!session?.user) {
      return new ChatSDKError("unauthorized:chat").toResponse();
    }

    const userType: UserType = session.user.type;
    const backendUserId = session.user.backendUserId || session.user.id;

    // Rate limit: 24시간 메시지 수 확인
    const countRes = await callBackendAPI(
      `/api/v1/chat/users/${backendUserId}/message-count?hours=24`
    );
    if (countRes.ok) {
      const { count } = await countRes.json();
      if (count > entitlementsByUserType[userType].maxMessagesPerDay) {
        return new ChatSDKError("rate_limit:chat").toResponse();
      }
    }

    // text 파트는 content로, file 파트는 attachments로 전달한다.
    // (이전에는 file 파트를 폐기해 첨부가 백엔드에 도달하지 못했다)
    const messageContent = extractTextContent(message.parts);
    const messageAttachments = extractAttachments(message.parts);

    // 기존 conversation 조회 (id = FE chat UUID = backendConversationId)
    let conversationId: string | null = null;
    const existingRes = await callBackendAPI(`/api/v1/chat/conversations/${id}`);

    if (existingRes.ok) {
      const existingConv = await existingRes.json();
      if (existingConv.user_id !== backendUserId) {
        return new ChatSDKError("forbidden:chat").toResponse();
      }
      conversationId = id;
    } else {
      // 신규 conversation 생성
      try {
        const createRes = await callBackendAPI("/api/v1/chat/conversations", {
          method: "POST",
          body: JSON.stringify({
            user_id: backendUserId,
            conversation_id: id,
            title: "New chat",
            model_name: mapToBackendModelName(selectedChatModel),
            mode: "standard",
            temperature: 0.7,
            visibility: selectedVisibilityType,
            // FE chat UUID를 conversation_id로 사용해 두 시스템 ID 일치
            metadata: { fe_chat_id: id },
          }),
        });

        if (!createRes.ok) {
          throw new Error("Failed to create conversation in backend");
        }

        const convData = await createRes.json();
        conversationId = convData.conversation_id;

        if (!conversationId) {
          throw new Error("Backend did not return conversation_id");
        }

        // 비동기 타이틀 생성 (non-blocking)
        generateTitleFromUserMessage({
          conversationId,
          userMessage: messageContent,
        }).then((title) => {
          callBackendAPI(`/api/v1/chat/conversations/${conversationId}`, {
            method: "PATCH",
            body: JSON.stringify({ title }),
          });
        }).catch(() => {});
      } catch (error) {
        console.error("Failed to create backend conversation:", error);
        return new ChatSDKError("offline:chat", "Failed to create conversation in backend").toResponse();
      }
    }

    // Backend 스트리밍 호출.
    // `request.signal`을 전달해 클라이언트가 정지하면 백엔드 스트림도 함께 끊는다.
    // (전달하지 않으면 사용자가 정지해도 백엔드는 계속 생성하고 계속 과금된다)
    const backendStreamResponse = await callBackendAPI(
      `/api/v1/chat/conversations/${conversationId}/messages/stream`,
      {
        method: "POST",
        signal: request.signal,
        body: JSON.stringify({
          content: messageContent,
          role: "user",
          attachments: messageAttachments,
          metadata: {
            fe_chat_id: id,
            model: mapToBackendModelName(selectedChatModel),
            visibility: selectedVisibilityType,
            autonomy_level: autonomyLevel,
          },
        }),
      }
    );

    if (!backendStreamResponse.ok) {
      console.error("Backend streaming error:", await backendStreamResponse.text());
      return new ChatSDKError("offline:chat").toResponse();
    }

    const transformStream = new TransformStream({
      async transform(chunk, controller) {
        controller.enqueue(chunk);
      },
      async flush(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
      },
    });

    const responseStream = backendStreamResponse.body?.pipeThrough(transformStream);

    return new Response(responseStream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
        "X-OpenResponses-Version": "2024-01-01",
        // FE가 conversation_id를 알 수 있도록 헤더로 전달
        "X-Conversation-Id": conversationId ?? "",
      },
    });
  } catch (error) {
    const vercelId = request.headers.get("x-vercel-id");

    if (error instanceof ChatSDKError) {
      return error.toResponse();
    }

    // 클라이언트가 정지를 눌러 요청이 취소된 경우는 에러가 아니다.
    // 백엔드 스트림도 signal 전파로 함께 끊긴다.
    if (isAbortError(error)) {
      return new Response(null, { status: 499 });
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

  const backendUserId = session.user.backendUserId || session.user.id;

  // 소유권 확인
  const convRes = await callBackendAPI(`/api/v1/chat/conversations/${id}`);
  if (!convRes.ok) {
    return new ChatSDKError("not_found:chat").toResponse();
  }

  const conv = await convRes.json();
  if (conv.user_id !== backendUserId) {
    return new ChatSDKError("forbidden:chat").toResponse();
  }

  const deleteRes = await callBackendAPI(`/api/v1/chat/conversations/${id}`, {
    method: "DELETE",
  });

  if (!deleteRes.ok) {
    return new ChatSDKError("bad_request:database").toResponse();
  }

  return Response.json(adaptBEConversation(conv), { status: 200 });
}
