"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { useRouter, usePathname } from "next/navigation";
import { MessageSquare, Plus, Trash2, Archive, Home } from "lucide-react";

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();

  const {
    conversations,
    currentConversationId,
    createConversation,
    setCurrentConversation,
    deleteConversation,
    archiveConversation,
  } = useChatStore();

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  const handleNewChat = async () => {
    router.push('/');
  };

  const handleConversationClick = (conversationId: string) => {
    // Navigate to the chat page
    router.push(`/chat/${conversationId}`);
  };

  const handleDeleteConversation = async (conversationId: string) => {
    if (!confirm("Are you sure you want to delete this conversation?")) {
      return;
    }

    await deleteConversation(conversationId);

    // If we deleted the current conversation, redirect to home
    if (conversationId === currentConversationId) {
      router.push('/');
    }
  };

  return (
    <div className="w-64 bg-claude-darker border-r border-claude-border flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-claude-border space-y-2">
        <button
          onClick={() => router.push('/')}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-claude-light hover:bg-claude-border text-claude-text rounded-lg transition-colors font-medium"
        >
          <Home size={18} />
          <span>Home</span>
        </button>
        <button
          onClick={handleNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary-hover text-white rounded-lg transition-colors font-medium"
        >
          <Plus size={18} />
          <span>New Chat</span>
        </button>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-2 space-y-1">
          {conversations.length === 0 ? (
            <div className="p-4 text-center text-claude-text-secondary text-sm">
              No conversations yet
            </div>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.conversation_id}
                className={`
                  group relative flex items-center gap-3 p-3 rounded-lg cursor-pointer
                  transition-colors
                  ${
                    pathname === `/chat/${conversation.conversation_id}`
                      ? "bg-claude-light"
                      : "hover:bg-claude-dark"
                  }
                `}
                onClick={() => handleConversationClick(conversation.conversation_id)}
              >
                <MessageSquare
                  size={16}
                  className="flex-shrink-0 text-claude-text-secondary"
                />

                <div className="flex-1 min-w-0">
                  <div className="text-sm text-claude-text truncate font-medium">
                    {conversation.title}
                  </div>
                  <div className="text-xs text-claude-text-secondary mt-0.5">
                    {formatDate(conversation.updated_at)} · {conversation.message_count}{" "}
                    msgs
                  </div>
                </div>

                {/* Action buttons - shown on hover */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      archiveConversation(conversation.conversation_id);
                    }}
                    className="p-1 rounded hover:bg-claude-border transition-colors"
                    title="Archive"
                  >
                    <Archive size={14} className="text-claude-text-secondary" />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteConversation(conversation.conversation_id);
                    }}
                    className="p-1 rounded hover:bg-red-500/20 transition-colors"
                    title="Delete"
                  >
                    <Trash2 size={14} className="text-red-400" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-claude-border">
        <div className="text-xs text-claude-text-secondary text-center">
          NEOS
        </div>
        <div className="text-xs text-claude-text-secondary text-center mt-1">
          {conversations.length} conversations
        </div>
      </div>
    </div>
  );
}
