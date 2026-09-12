import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { Chat } from "@/components/chat";
import { DataStreamHandler } from "@/components/data-stream-handler";
import { loadPageCatalog } from "@/lib/ai/catalog";
import { generateUUID } from "@/lib/utils";
import { auth } from "../(auth)/auth";


export default function Page() {
  return (
    <Suspense fallback={<div className="flex h-dvh" />}>
      <NewChatPage />
    </Suspense>
  );
}

async function NewChatPage() {
  const session = await auth();

  if (!session) {
    redirect("/api/auth/guest");
  }

  const id = generateUUID();

  const cookieStore = await cookies();
  const { catalog, modelId, rewriteTo } = await loadPageCatalog(
    cookieStore.get("chat-model")?.value
  );

  return (
    <>
      <Chat
        autoResume={false}
        catalog={catalog}
        cookieRewriteTo={rewriteTo}
        id={id}
        initialChatModel={modelId}
        initialMessages={[]}
        initialVisibilityType="private"
        isReadonly={false}
        key={id}
      />
      <DataStreamHandler />
    </>
  );
}
