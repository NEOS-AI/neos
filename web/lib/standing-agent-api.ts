import { backendErrorMessage } from "@/lib/backend-error";

/**
 * 상시 에이전트의 웹 "에이전트 대화" id (트랙 Q8d).
 *
 * 에이전트가 없거나 기능이 꺼져 있으면 null 이다 -- 오류가 아니라 "아직 없음"이다.
 * 그 밖의 실패는 읽을 수 있는 message 의 Error 로 던진다.
 */
export async function openAgentConversation(): Promise<string | null> {
  const response = await fetch("/api/standing-agent/conversation", {
    method: "POST",
  });
  if (response.status === 404) {
    return null;
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      backendErrorMessage(body, "Could not open the agent conversation")
    );
  }
  const conversationId = (body as { conversationId?: unknown }).conversationId;
  if (typeof conversationId !== "string" || !conversationId) {
    throw new Error("Could not open the agent conversation");
  }
  return conversationId;
}
