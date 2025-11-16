"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { useRouter, usePathname } from "next/navigation";
import { MessageSquare, Plus, Trash2, Home, Search, X } from "lucide-react";
import { useState, useEffect } from "react";

interface SidebarProps {
  isMobileOpen?: boolean;
  onMobileClose?: () => void;
}

export default function Sidebar({ isMobileOpen = false, onMobileClose }: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [searchQuery, setSearchQuery] = useState("");

  // Close sidebar on route change (mobile)
  useEffect(() => {
    if (onMobileClose) {
      onMobileClose();
    }
  }, [pathname]);

  const {
    conversations,
    currentConversationId,
    deleteConversation,
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
    router.push(`/chat/${conversationId}`);
  };

  const handleDeleteConversation = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) {
      return;
    }

    await deleteConversation(conversationId);

    if (conversationId === currentConversationId) {
      router.push('/');
    }
  };

  const filteredConversations = conversations.filter(conv =>
    conv.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <>
      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <nav
        className={`
          w-[280px] bg-bg-surface border-r border-line-soft flex flex-col h-screen
          sticky top-0 z-50
          lg:translate-x-0
          ${isMobileOpen ? "translate-x-0" : "-translate-x-full"}
          lg:static fixed
          transition-transform duration-300 ease-in-out
        `}
        aria-label="Main navigation"
      >
        {/* Header */}
        <div className="p-4 space-y-3 border-b border-line-soft">
          {/* Mobile close button & Logo */}
          <div className="flex items-center justify-between">
            <button
              onClick={() => router.push('/')}
              className="
                flex items-center gap-3 px-3 py-2
                text-text-primary hover:text-brand-accent
                transition-colors
                group flex-1
              "
              aria-label="Go to home"
            >
              <div className="w-7 h-7 rounded-lg bg-brand-accent/10 flex items-center justify-center text-brand-accent font-bold text-sm">
                N
              </div>
              <span className="text-sm font-semibold">NEOS</span>
            </button>

            {/* Close button (mobile only) */}
            {onMobileClose && (
              <button
                onClick={onMobileClose}
                className="
                  lg:hidden p-2 rounded-lg
                  text-text-secondary hover:text-text-primary hover:bg-action-hover
                  transition-colors
                "
                aria-label="Close sidebar"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>

        {/* New Chat Button */}
        <button
          onClick={handleNewChat}
          className="
            w-full flex items-center justify-center gap-2 px-4 py-2.5
            bg-brand-accent/10 hover:bg-brand-accent/20
            text-brand-accent rounded-2xl
            transition-all duration-200
            font-medium text-sm
            hover:shadow-glow
            focus:outline-none focus:ring-2 focus:ring-brand-accent/50
          "
          aria-label="Start new chat"
        >
          <Plus className="w-4 h-4" />
          <span>New Chat</span>
        </button>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
              w-full pl-9 pr-3 py-2
              bg-chip-bg border border-chip-line rounded-xl
              text-text-primary placeholder:text-text-muted text-sm
              focus:outline-none focus:ring-2 focus:ring-brand-accent/50 focus:border-brand-accent/50
              transition-all duration-200
            "
            aria-label="Search conversations"
          />
        </div>
      </div>

      {/* Conversations Section */}
      <div className="flex-1 overflow-y-auto">
        {/* Section Header */}
        <div className="px-4 py-3">
          <h2 className="text-label-s text-text-muted uppercase font-semibold">
            Conversations
          </h2>
        </div>

        {/* Conversation List */}
        <div className="px-2 pb-2 space-y-1">
          {filteredConversations.length === 0 ? (
            <div className="px-4 py-8 text-center text-text-muted text-sm">
              {searchQuery ? "No conversations found" : "No conversations yet"}
            </div>
          ) : (
            filteredConversations.map((conversation) => {
              const isActive = pathname === `/chat/${conversation.conversation_id}`;
              return (
                <div
                  key={conversation.conversation_id}
                  className={`
                    group relative flex items-center gap-3 px-3 py-2.5 rounded-xl
                    cursor-pointer transition-all duration-150
                    ${isActive
                      ? "bg-brand-accent/10 border-l-2 border-brand-accent"
                      : "hover:bg-action-hover border-l-2 border-transparent"
                    }
                  `}
                  onClick={() => handleConversationClick(conversation.conversation_id)}
                >
                  <MessageSquare
                    className={`flex-shrink-0 w-4 h-4 ${
                      isActive ? "text-brand-accent" : "text-text-muted"
                    }`}
                  />

                  <div className="flex-1 min-w-0">
                    <div className={`text-sm truncate font-medium ${
                      isActive ? "text-brand-accent" : "text-text-primary"
                    }`}>
                      {conversation.title}
                    </div>
                    <div className="text-xs text-text-muted mt-0.5">
                      {formatDate(conversation.updated_at)} · {conversation.message_count}
                    </div>
                  </div>

                  {/* Delete button - shown on hover */}
                  <button
                    onClick={(e) => handleDeleteConversation(conversation.conversation_id, e)}
                    className="
                      opacity-0 group-hover:opacity-100
                      p-1.5 rounded-lg
                      hover:bg-red-500/20 transition-all
                      focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500/50
                    "
                    title="Delete conversation"
                    aria-label="Delete conversation"
                  >
                    <Trash2 className="w-3.5 h-3.5 text-red-400" />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-line-soft">
        <div className="text-xs text-text-muted text-center">
          {conversations.length} {conversations.length === 1 ? "conversation" : "conversations"}
        </div>
      </div>
      </nav>
    </>
  );
}
