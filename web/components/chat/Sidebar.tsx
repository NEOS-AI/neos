"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { useRouter, usePathname } from "next/navigation";
import { MessageSquare, Plus, Trash2, Home, Search, LogIn, UserPlus, User, LogOut } from "lucide-react";
import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { formatTimestamp } from "@/lib/utils";
import { useAuth } from "@/lib/contexts/auth-context";

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [searchQuery, setSearchQuery] = useState("");
  const conversationRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);
  const { user, isAuthenticated, isLoading, logout } = useAuth();

  const {
    conversations,
    currentConversationId,
    deleteConversation,
  } = useChatStore();

  const filteredConversations = conversations.filter(conv =>
    (conv.title || 'New Chat').toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Update refs array when conversations change
  useEffect(() => {
    conversationRefs.current = conversationRefs.current.slice(0, filteredConversations.length);
  }, [filteredConversations.length]);

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
      className="w-[280px] bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col h-full animate-slide-in-left"
      aria-label="Main navigation"
    >
      {/* Header */}
      <div className="p-4 space-y-3 border-b border-gray-200 dark:border-gray-800 animate-fade-in-down">
        {/* Logo & Home */}
        <button
          onClick={() => router.push('/')}
          className="
            w-full flex items-center gap-3 px-3 py-2
            text-gray-900 dark:text-gray-100 hover:text-orange-600 dark:hover:text-orange-400
            transition-all duration-200 hover:scale-105 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800
            group animate-scale-in
          "
          aria-label="Go to home"
        >
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-700 via-slate-800 to-indigo-800 flex items-center justify-center text-white font-bold text-base shadow-md ring-2 ring-blue-700/20 group-hover:shadow-lg transition-all duration-300 group-hover:animate-pulse-subtle">
            N
          </div>
          <span className="text-sm font-semibold">NEOS</span>
        </button>

        {/* New Chat Button */}
        <button
          onClick={handleNewChat}
          className="
            w-full flex items-center justify-center gap-2 px-4 py-2.5
            bg-gradient-to-br from-blue-700/10 via-slate-800/10 to-indigo-800/10
            hover:from-blue-700/20 hover:via-slate-800/20 hover:to-indigo-800/20
            text-brand-accent rounded-2xl
            transition-all duration-300
            font-medium text-sm
            hover:shadow-lg hover:scale-105 active:scale-95
            focus:outline-none focus:ring-2 focus:ring-brand-accent/50
            animate-scale-in
          "
          style={{ animationDelay: '100ms' }}
          aria-label="Start new chat"
        >
          <Plus className="w-4 h-4" />
          <span>New Chat</span>
        </button>

        {/* Search */}
        <div className="relative animate-scale-in" style={{ animationDelay: '200ms' }}>
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-gray-500 transition-colors" />
          <input
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
              w-full pl-9 pr-3 py-2
              bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl
              text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 text-sm
              focus:outline-none focus:ring-2 focus:ring-brand-accent/50 focus:border-brand-accent/50
              transition-all duration-200 hover:border-gray-300 dark:hover:border-gray-600
            "
            aria-label="Search conversations"
          />
        </div>
      </div>

      {/* Conversations Section */}
      <div className="flex-1 overflow-y-auto">
        {/* Section Header */}
        <div className="px-4 py-3">
          <h2 className="text-xs text-gray-500 dark:text-gray-400 uppercase font-semibold tracking-wider">
            Conversations
          </h2>
        </div>

        {/* Conversation List */}
        <div className="px-2 pb-2 space-y-1" role="list" aria-label="Conversations">
          {filteredConversations.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-500 dark:text-gray-400 text-sm animate-fade-in">
              {searchQuery ? "No conversations found" : "No conversations yet"}
            </div>
          ) : (
            filteredConversations.map((conversation, index) => {
              const isActive = pathname === `/chat/${conversation.conversation_id}`;
              return (
                <div
                  key={conversation.conversation_id}
                  ref={(el) => { conversationRefs.current[index] = el }}
                  role="listitem"
                  tabIndex={isActive ? 0 : -1}
                  className={`
                    group relative flex items-center gap-3 px-3 py-2.5 rounded-xl mx-1
                    cursor-pointer transition-all duration-200
                    focus:outline-none focus:ring-2 focus:ring-brand-accent/50
                    animate-fade-in-up
                    ${isActive
                      ? "bg-gradient-to-r from-blue-700/10 to-indigo-800/10 border-l-2 border-brand-accent shadow-sm"
                      : "hover:bg-gray-50 dark:hover:bg-gray-800 border-l-2 border-transparent hover:scale-[1.02] hover:shadow-sm"
                    }
                  `}
                  style={{ animationDelay: `${index * 30}ms` }}
                  onClick={() => handleConversationClick(conversation.conversation_id)}
                  onKeyDown={(e) => handleKeyDown(e, index, conversation.conversation_id)}
                  aria-label={`${conversation.title}, ${conversation.message_count} messages, ${formatTimestamp(conversation.updated_at)}`}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <MessageSquare
                    className={`flex-shrink-0 w-4 h-4 transition-all duration-200 ${
                      isActive ? "text-brand-accent" : "text-gray-400 dark:text-gray-500 group-hover:text-brand-accent/70"
                    }`}
                  />

                  <div className="flex-1 min-w-0">
                    <div className={`text-sm truncate font-medium transition-colors ${
                      isActive ? "text-brand-accent" : "text-gray-900 dark:text-gray-100"
                    }`}>
                      {conversation.title || "New Chat"}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      {formatTimestamp(conversation.updated_at)} · {conversation.message_count}
                    </div>
                  </div>

                  {/* Delete button - shown on hover */}
                  <button
                    onClick={(e) => handleDeleteConversation(conversation.conversation_id, e)}
                    className="
                      opacity-0 group-hover:opacity-100
                      p-1.5 rounded-lg
                      hover:bg-red-100 dark:hover:bg-red-900/30 transition-all duration-200 hover:scale-110
                      focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500/50
                    "
                    title="Delete conversation"
                    aria-label="Delete conversation"
                  >
                    <Trash2 className="w-3.5 h-3.5 text-red-600 dark:text-red-400 transition-transform group-hover:rotate-12" />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Footer - Auth Section */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-800 animate-fade-in-up" style={{ animationDelay: '300ms' }}>
        {!isLoading && !isAuthenticated ? (
          /* Not logged in - Show Sign In / Sign Up buttons */
          <div className="space-y-2">
            <button
              onClick={() => router.push('/login')}
              className="
                w-full flex items-center justify-center gap-2 px-4 py-2.5
                bg-action-hover hover:bg-chip-bg
                text-text-primary rounded-xl
                transition-all duration-200
                font-medium text-sm
                hover:shadow-md hover:scale-105 active:scale-95
                focus:outline-none focus:ring-2 focus:ring-brand-accent/50
              "
            >
              <LogIn className="w-4 h-4" />
              <span>Sign In</span>
            </button>
            <button
              onClick={() => router.push('/register')}
              className="
                w-full flex items-center justify-center gap-2 px-4 py-2.5
                bg-gradient-to-br from-blue-700/10 via-slate-800/10 to-indigo-800/10
                hover:from-blue-700/20 hover:via-slate-800/20 hover:to-indigo-800/20
                text-brand-accent rounded-xl
                transition-all duration-200
                font-medium text-sm
                hover:shadow-md hover:scale-105 active:scale-95
                focus:outline-none focus:ring-2 focus:ring-brand-accent/50
              "
            >
              <UserPlus className="w-4 h-4" />
              <span>Sign Up</span>
            </button>
          </div>
        ) : isAuthenticated && user ? (
          /* Logged in - Show user profile */
          <div className="space-y-3">
            <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-800">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-700/20 via-slate-800/20 to-indigo-800/20 flex items-center justify-center text-brand-accent font-semibold text-sm">
                {user.username?.[0]?.toUpperCase() || user.email?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                  {user.username || user.email?.split('@')[0]}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                  {user.email}
                </div>
              </div>
            </div>
            <button
              onClick={async () => {
                try {
                  await logout();
                  router.push('/');
                } catch (error) {
                  console.error('Logout failed:', error);
                }
              }}
              className="
                w-full flex items-center justify-center gap-2 px-4 py-2
                text-gray-600 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20
                rounded-xl transition-all duration-200
                text-sm font-medium
                hover:scale-105 active:scale-95
                focus:outline-none focus:ring-2 focus:ring-red-500/50
              "
            >
              <LogOut className="w-4 h-4" />
              <span>Sign Out</span>
            </button>
          </div>
        ) : null}
      </div>
    </nav>
  );
}
