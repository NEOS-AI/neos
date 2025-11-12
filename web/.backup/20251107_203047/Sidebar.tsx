"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Plus, MessageSquare, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatTimestamp } from "@/lib/utils";

export default function Sidebar() {
  const {
    sessions,
    currentSessionId,
    createSession,
    setCurrentSession,
    deleteSession,
  } = useChatStore();

  return (
    <aside className="w-64 bg-claude-darker border-r border-claude-border flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-claude-border/50">
        <button
          onClick={createSession}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-transparent hover:bg-claude-dark border border-claude-border hover:border-claude-text-secondary/40 text-claude-text rounded-lg transition-all duration-200 text-sm font-medium"
        >
          <Plus size={16} strokeWidth={2} />
          New chat
        </button>
      </div>

      {/* Chat History */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {sessions.length === 0 ? (
          <div className="text-center text-claude-text-secondary/60 text-sm py-8 px-4">
            Your conversations will appear here
          </div>
        ) : (
          <div className="space-y-0.5">
            {sessions.map((session) => (
              <div
                key={session.id}
                className={cn(
                  "group relative flex items-center gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-150",
                  currentSessionId === session.id
                    ? "bg-claude-dark text-claude-text"
                    : "text-claude-text-secondary hover:bg-claude-dark/50 hover:text-claude-text"
                )}
                onClick={() => setCurrentSession(session.id)}
              >
                <MessageSquare size={16} className="flex-shrink-0 opacity-70" />

                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate leading-snug">
                    {session.title}
                  </div>
                  <div className="text-xs text-claude-text-secondary/60 mt-0.5">
                    {formatTimestamp(session.updatedAt)}
                  </div>
                </div>

                {/* Delete Button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (
                      confirm("Delete this conversation?")
                    ) {
                      deleteSession(session.id);
                    }
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-500/10 hover:text-red-400 rounded transition-all"
                  aria-label="Delete chat"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-claude-border/50">
        <div className="flex items-center justify-center gap-2">
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white font-bold text-xs">
            N
          </div>
          <div className="text-xs text-claude-text-secondary">
            NEOS
          </div>
        </div>
      </div>
    </aside>
  );
}
