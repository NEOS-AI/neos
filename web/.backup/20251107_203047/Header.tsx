"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Menu, Sparkles } from "lucide-react";
import { useState } from "react";

export default function Header() {
  const { currentSession } = useChatStore();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

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

        {/* Session Title */}
        {currentSession && currentSession.messages.length > 0 && (
          <div className="flex items-center gap-2 text-sm text-claude-text-secondary">
            <span className="opacity-40">•</span>
            <span className="truncate max-w-xs">
              {currentSession.title}
            </span>
          </div>
        )}
      </div>

      {/* Pro Badge (Optional) */}
      <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/20 rounded-full">
        <Sparkles size={14} className="text-orange-400" />
        <span className="text-xs font-medium text-orange-400">AI Powered</span>
      </div>
    </header>
  );
}
