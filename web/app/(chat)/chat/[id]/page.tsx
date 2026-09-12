import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { auth } from "@/app/(auth)/auth";
import { Chat } from "@/components/chat";
import { DataStreamHandler } from "@/components/data-stream-handler";
import { loadPageCatalog } from "@/lib/ai/catalog";
import { adaptBEConversation } from "@/lib/adapters/chat-adapters";
import { callBackendAPI } from "@/lib/backend-api";
import type { ChatMessage } from "@/lib/types";
import { convertBackendMessagesToUI } from "@/lib/utils";


export default function Page(props: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="flex h-dvh" />}>
      <ChatPage params={props.params} />
    </Suspense>
  );
}

async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const session = await auth();

  if (!session) {
    redirect("/api/auth/guest");
  }

  const backendUserId = session.user.backendUserId || session.user.id;

  // BE에서 conversation 조회 (id = conversation_id)
  const convRes = await callBackendAPI(`/api/v1/chat/conversations/${id}`);

  if (!convRes.ok) {
    redirect("/");
  }

  const convRaw = await convRes.json();
  const chat = adaptBEConversation(convRaw);

  if (chat.visibility === "private") {
    if (!session.user) return notFound();
    if (convRaw.user_id !== backendUserId) return notFound();
  }

  // 메시지 이력 로드
  let uiMessages: ChatMessage[] = [];

  try {
    const msgRes = await callBackendAPI(
      `/api/v1/chat/conversations/${id}/messages?limit=100`
    );

    if (msgRes.ok) {
      const backendMessages = await msgRes.json();
      uiMessages = convertBackendMessagesToUI(backendMessages);
    }
  } catch (error) {
    console.error("Error fetching backend messages:", error);
  }

  const cookieStore = await cookies();
  const { catalog, modelId, rewriteTo } = await loadPageCatalog(
    cookieStore.get("chat-model")?.value
  );

  return (
    <>
      <Chat
        // 재개는 백엔드 이벤트 재생(Phase 3)이 붙기 전까지 비활성화한다.
        // 예전 동작은 재개가 아니라 워크플로우 재실행이라 새로고침만으로 재과금됐다.
        // (use-chat-stream.ts의 resumeStream도 no-op으로 이중 차단)
        autoResume={false}
        catalog={catalog}
        cookieRewriteTo={rewriteTo}
        id={chat.id}
        initialChatModel={modelId}
        initialMessages={uiMessages}
        initialVisibilityType={chat.visibility}
        isReadonly={convRaw.user_id !== backendUserId}
      />
      <DataStreamHandler />
    </>
  );
}
