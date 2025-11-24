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
    <header className="h-16 border-b border-gray-200 dark:border-gray-800 flex items-center px-4 sm:px-6 bg-white dark:bg-gray-900 backdrop-blur-sm">
      <button
        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        className="lg:hidden p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-all duration-200 hover:scale-105 active:scale-95 mr-3"
        aria-label="Toggle sidebar"
      >
        <Menu size={20} className="text-gray-700 dark:text-gray-300" />
      </button>

      <div className="flex items-center gap-3 flex-1">
        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-700 via-slate-800 to-indigo-800 flex items-center justify-center text-white font-bold text-base shadow-md ring-2 ring-blue-700/20">
            N
          </div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">NEOS</h1>
        </div>

        {/* Conversation Title */}
        {currentConversation && currentConversation.message_count > 0 && (
          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <span className="opacity-40">•</span>
            <span className="truncate max-w-xs font-medium">
              {currentConversation.title}
            </span>
          </div>
        )}
      </div>

      {/* AI Badge */}
      <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-blue-700/10 to-indigo-800/10 border border-blue-700/20 rounded-full">
        <Sparkles size={14} className="text-blue-700 dark:text-blue-500" />
        <span className="text-xs font-medium text-blue-700 dark:text-blue-400">AI Powered</span>
      </div>

      {/* User Info & Auth */}
      <div className="flex items-center gap-2 ml-4">
        {isAuthenticated && user ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
              <User size={14} className="text-gray-600 dark:text-gray-400" />
              <span className="text-sm text-gray-900 dark:text-gray-100 font-medium">{user.username}</span>
            </div>
            <button
              onClick={handleLogout}
              className="p-2 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all duration-200 hover:scale-105 active:scale-95 group"
              title="Logout"
              aria-label="Logout"
            >
              <LogOut size={16} className="text-gray-600 dark:text-gray-400 group-hover:text-red-600 dark:group-hover:text-red-400 transition-colors" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => router.push('/login')}
            className="px-4 py-2 bg-gradient-to-br from-blue-700/10 via-slate-800/10 to-indigo-800/10 hover:from-blue-700/20 hover:via-slate-800/20 hover:to-indigo-800/20 text-brand-accent text-sm font-medium rounded-lg transition-all duration-200 hover:scale-105 active:scale-95 shadow-md"
          >
            Sign In
          </button>
        )}
      </div>
    </header>
  );
}
