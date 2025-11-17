"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { useRouter, usePathname } from "next/navigation";
import { MessageSquare, Plus, Trash2, Home, Search } from "lucide-react";
import { useState, useRef, useEffect, KeyboardEvent } from "react";

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [searchQuery, setSearchQuery] = useState("");
  const conversationRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);

  const {
    conversations,
    currentConversationId,
    deleteConversation,
  } = useChatStore();

  const filteredConversations = conversations.filter(conv =>
    conv.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Update refs array when conversations change
  useEffect(() => {
    conversationRefs.current = conversationRefs.current.slice(0, filteredConversations.length);
  }, [filteredConversations.length]);

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

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>, index: number, conversationId: string) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        const nextIndex = Math.min(index + 1, filteredConversations.length - 1);
        conversationRefs.current[nextIndex]?.focus();
        setFocusedIndex(nextIndex);
        break;

      case 'ArrowUp':
        e.preventDefault();
        const prevIndex = Math.max(index - 1, 0);
        conversationRefs.current[prevIndex]?.focus();
        setFocusedIndex(prevIndex);
        break;

      case 'Home':
        e.preventDefault();
        conversationRefs.current[0]?.focus();
        setFocusedIndex(0);
        break;

      case 'End':
        e.preventDefault();
        const lastIndex = filteredConversations.length - 1;
        conversationRefs.current[lastIndex]?.focus();
        setFocusedIndex(lastIndex);
        break;

      case 'Enter':
      case ' ':
        e.preventDefault();
        handleConversationClick(conversationId);
        break;

      case 'Delete':
      case 'Backspace':
        e.preventDefault();
        if (confirm("Delete this conversation?")) {
          deleteConversation(conversationId);
          if (conversationId === currentConversationId) {
            router.push('/');
          }
        }
        break;
    }
  };

  return (
    <nav
      className="w-[280px] bg-bg-surface border-r border-line-soft flex flex-col h-full"
      aria-label="Main navigation"
    >
      {/* Header */}
      <div className="p-4 space-y-3 border-b border-line-soft">
        {/* Logo & Home */}
        <button
          onClick={() => router.push('/')}
          className="
            w-full flex items-center gap-3 px-3 py-2
            text-text-primary hover:text-brand-accent
            transition-colors
            group
          "
          aria-label="Go to home"
        >
          <div className="w-7 h-7 rounded-lg bg-brand-accent/10 flex items-center justify-center text-brand-accent font-bold text-sm">
            N
          </div>
          <span className="text-sm font-semibold">NEOS</span>
        </button>

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
        <div className="px-2 pb-2 space-y-1" role="list" aria-label="Conversations">
          {filteredConversations.length === 0 ? (
            <div className="px-4 py-8 text-center text-text-muted text-sm">
              {searchQuery ? "No conversations found" : "No conversations yet"}
            </div>
          ) : (
            filteredConversations.map((conversation, index) => {
              const isActive = pathname === `/chat/${conversation.conversation_id}`;
              return (
                <div
                  key={conversation.conversation_id}
                  ref={(el) => (conversationRefs.current[index] = el)}
                  role="listitem"
                  tabIndex={isActive ? 0 : -1}
                  className={`
                    group relative flex items-center gap-3 px-3 py-2.5 rounded-xl
                    cursor-pointer transition-all duration-150
                    focus:outline-none focus:ring-2 focus:ring-brand-accent/50
                    ${isActive
                      ? "bg-brand-accent/10 border-l-2 border-brand-accent"
                      : "hover:bg-action-hover border-l-2 border-transparent"
                    }
                  `}
                  onClick={() => handleConversationClick(conversation.conversation_id)}
                  onKeyDown={(e) => handleKeyDown(e, index, conversation.conversation_id)}
                  aria-label={`${conversation.title}, ${conversation.message_count} messages, ${formatDate(conversation.updated_at)}`}
                  aria-current={isActive ? 'page' : undefined}
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
  );
}
