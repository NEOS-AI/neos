import { auth } from "@/app/(auth)/auth";
import { callBackendAPI } from "@/lib/backend-api";
import { ChatSDKError } from "@/lib/errors";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const chatId = searchParams.get("chatId");

  if (!chatId) {
    return new ChatSDKError(
      "bad_request:api",
      "Parameter chatId is required."
    ).toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:vote").toResponse();
  }

  // 백엔드 API 호출
  try {
    const response = await callBackendAPI(`/api/v1/votes/${chatId}`);

    if (!response.ok) {
      const error = await response.json();
      return Response.json(error, { status: response.status });
    }

    const votes = await response.json();
    return Response.json(votes, { status: 200 });
  } catch (error) {
    console.error("Vote GET error:", error);
    return new ChatSDKError("offline:vote").toResponse();
  }
}

export async function PATCH(request: Request) {
  const {
    chatId,
    messageId,
    type,
  }: { chatId: string; messageId: string; type: "up" | "down" } =
    await request.json();

  if (!chatId || !messageId || !type) {
    return new ChatSDKError(
      "bad_request:api",
      "Parameters chatId, messageId, and type are required."
    ).toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:vote").toResponse();
  }

  // 백엔드 API 호출
  try {
    const response = await callBackendAPI(`/api/v1/votes`, {
      method: "POST",
      body: JSON.stringify({
        chat_id: chatId,
        message_id: messageId,
        is_upvoted: type === "up",
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      return Response.json(error, { status: response.status });
    }

    const vote = await response.json();
    return Response.json(vote, { status: 200 });
  } catch (error) {
    console.error("Vote PATCH error:", error);
    return new ChatSDKError("offline:vote").toResponse();
  }
}
