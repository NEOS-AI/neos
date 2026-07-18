import type { Chat } from "@/lib/db/schema";

interface BEConversationResponse {
  conversation_id: string;
  user_id: string;
  title?: string | null;
  status: string;
  visibility?: string;
  is_pinned?: boolean;
  created_at: string;
  [key: string]: unknown;
}

interface BEConversationListResponse {
  conversations: BEConversationResponse[];
  total_count: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export function adaptBEConversation(conv: BEConversationResponse): Chat {
  return {
    id: conv.conversation_id,
    createdAt: new Date(conv.created_at),
    title: conv.title ?? "New chat",
    userId: conv.user_id,
    visibility: (conv.visibility === "public" ? "public" : "private") as
      | "public"
      | "private",
    backendConversationId: conv.conversation_id,
  };
}

export function adaptBEConversationList(
  data: BEConversationListResponse
): { chats: Chat[]; hasMore: boolean; nextCursor: string | null } {
  return {
    chats: data.conversations.map(adaptBEConversation),
    hasMore: data.has_more,
    nextCursor: data.next_cursor ?? null,
  };
}
