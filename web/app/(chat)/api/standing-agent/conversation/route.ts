import { NextResponse } from "next/server";
import { BackendAPIError, callBackendAPIWithJSON } from "@/lib/backend-api";
import { bffErrorResponse } from "@/lib/bff-error";

// 트랙 Q8d -- 상시 에이전트의 웹 "에이전트 대화"를 열거나 만든다. 그 대화는 보통 채팅
// 대화이고(FE 채팅 id = 백엔드 conversation_id), 백엔드가 에이전트 스레드에 붙여 둔다.
// 메시지 전송은 기존 채팅 경로 그대로다. 백엔드는 standing_agents · threads 가 둘 다
// 켜졌을 때만 이 라우트들을 마운트한다 -- 꺼져 있거나 에이전트가 없으면 404 다.
export async function POST() {
  try {
    const agent = await callBackendAPIWithJSON<{ agent_id: string }>(
      "/api/v1/standing-agents/me"
    );
    const result = await callBackendAPIWithJSON<{
      conversation_id: string;
      created: boolean;
    }>(
      `/api/v1/standing-agents/${encodeURIComponent(agent.agent_id)}/thread/web-conversation`,
      { method: "POST" }
    );
    return NextResponse.json({
      conversationId: result.conversation_id,
      created: result.created,
    });
  } catch (error: unknown) {
    if (error instanceof BackendAPIError && error.status === 404) {
      return NextResponse.json(
        { error: "No standing agent", code: "no_standing_agent" },
        { status: 404 }
      );
    }
    return bffErrorResponse(error, "Could not open the agent conversation");
  }
}
