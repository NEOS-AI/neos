"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Menu, Sparkles, LogOut, User } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/lib/contexts/auth-context";
import { useRouter } from "next/navigation";

export default function Header() {
  const router = useRouter();
  const { user, isAuthenticated, logout } = useAuth();

  // Use selector to properly subscribe to store changes
  const currentConversation = useChatStore((state) => {
    const current = state.conversations.find(
      (c) => c.conversation_id === state.currentConversationId
    );
    return current || null;
  });
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  return (
    <header className="h-14 border-b border-claude-border/50 flex items-center px-6 bg-claude-darker/80 backdrop-blur-sm">
      <button
        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        className="lg:hidden p-2 hover:bg-claude-dark rounded-lg transition-colors mr-3"
        aria-label="Toggle sidebar"
      >
        <Menu size={20} className="text-claude-text" />
      </button>

      <div className="flex items-center gap-3 flex-1">
        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white font-bold text-sm">
            N
          </div>
          <h1 className="text-base font-semibold text-claude-text">NEOS</h1>
        </div>

        {/* Conversation Title */}
        {currentConversation && currentConversation.message_count > 0 && (
          <div className="flex items-center gap-2 text-sm text-claude-text-secondary">
            <span className="opacity-40">•</span>
            <span className="truncate max-w-xs">
              {currentConversation.title}
            </span>
          </div>
        )}
      </div>

      {/* AI Badge */}
      <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/20 rounded-full">
        <Sparkles size={14} className="text-orange-400" />
        <span className="text-xs font-medium text-orange-400">AI Powered</span>
      </div>

      {/* User Info & Auth */}
      <div className="flex items-center gap-3 ml-4">
        {isAuthenticated && user ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-claude-dark border border-claude-border rounded-lg">
              <User size={14} className="text-claude-text-secondary" />
              <span className="text-sm text-claude-text">{user.username}</span>
            </div>
            <button
              onClick={handleLogout}
              className="p-2 hover:bg-claude-dark rounded-lg transition-colors group"
              title="Logout"
              aria-label="Logout"
            >
              <LogOut size={16} className="text-claude-text-secondary group-hover:text-red-400 transition-colors" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => router.push('/login')}
            className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-white text-sm rounded-lg transition-colors"
          >
            Sign In
          </button>
        )}
      </div>
    </header>
  );
}
