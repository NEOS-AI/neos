import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { auth } from "@/app/(auth)/auth";
import { Chat } from "@/components/chat";
import { DataStreamHandler } from "@/components/data-stream-handler";
import { DEFAULT_CHAT_MODEL } from "@/lib/ai/models";
import { callBackendAPI } from "@/lib/backend-api";
import { getChatById, getMessagesByChatId } from "@/lib/db/queries";
import type { ChatMessage } from "@/lib/types";
import { convertBackendMessagesToUI, convertToUIMessages } from "@/lib/utils";


export default function Page(props: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="flex h-dvh" />}>
      <ChatPage params={props.params} />
    </Suspense>
  );
}

async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const chat = await getChatById({ id });

  if (!chat) {
    redirect("/");
  }

  const session = await auth();

  if (!session) {
    redirect("/api/auth/guest");
  }

  if (chat.visibility === "private") {
    if (!session.user) {
      return notFound();
    }

    if (session.user.id !== chat.userId) {
      return notFound();
    }
  }

  // Load message history: prefer backend API, fallback to frontend DB
  let uiMessages: ChatMessage[] = [];

  if (chat.backendConversationId) {
    try {
      // Fetch messages from backend API
      const backendMessagesResponse = await callBackendAPI(
        `/api/v1/chat/conversations/${chat.backendConversationId}/messages?limit=100`
      );

      if (backendMessagesResponse.ok) {
        const backendMessages = await backendMessagesResponse.json();
        uiMessages = convertBackendMessagesToUI(backendMessages);
      } else {
        // Backend fetch failed, use frontend DB
        console.warn("Failed to fetch backend messages, using frontend DB");
        const messagesFromDb = await getMessagesByChatId({ id });
        uiMessages = convertToUIMessages(messagesFromDb);
      }
    } catch (error) {
      // Error occurred, use frontend DB
      console.error("Error fetching backend messages:", error);
      const messagesFromDb = await getMessagesByChatId({ id });
      uiMessages = convertToUIMessages(messagesFromDb);
    }
  } else {
    // No backendConversationId (legacy chat), use frontend DB
    const messagesFromDb = await getMessagesByChatId({ id });
    uiMessages = convertToUIMessages(messagesFromDb);
  }

  const cookieStore = await cookies();
  const chatModelFromCookie = cookieStore.get("chat-model");

  if (!chatModelFromCookie) {
    return (
      <>
        <Chat
          autoResume={true}
          id={chat.id}
          initialChatModel={DEFAULT_CHAT_MODEL}
          initialMessages={uiMessages}
          initialVisibilityType={chat.visibility}
          isReadonly={session?.user?.id !== chat.userId}
        />
        <DataStreamHandler />
      </>
    );
  }

  return (
    <>
      <Chat
        autoResume={true}
        id={chat.id}
        initialChatModel={chatModelFromCookie.value}
        initialMessages={uiMessages}
        initialVisibilityType={chat.visibility}
        isReadonly={session?.user?.id !== chat.userId}
      />
      <DataStreamHandler />
    </>
  );
}
