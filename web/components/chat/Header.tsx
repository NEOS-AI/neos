"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Menu } from "lucide-react";
import { useState } from "react";

export default function Header() {
  const { currentSession } = useChatStore();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <header className="h-14 border-b border-claude-border flex items-center px-4 bg-claude-dark">
      <button
        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        className="lg:hidden p-2 hover:bg-claude-light rounded-lg transition-colors mr-2"
        aria-label="Toggle sidebar"
      >
        <Menu size={20} />
      </button>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-white font-semibold">
            N
          </div>
          <h1 className="text-lg font-semibold text-claude-text">NEOS</h1>
        </div>

        {currentSession && (
          <>
            <span className="text-claude-text-secondary">/</span>
            <span className="text-claude-text-secondary text-sm truncate max-w-xs">
              {currentSession.title}
            </span>
          </>
        )}
      </div>
    </header>
  );
}
