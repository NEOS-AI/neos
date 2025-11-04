"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { MessageSquarePlus, Trash2 } from "lucide-react";
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
    <aside className="w-64 bg-claude-dark border-r border-claude-border flex flex-col">
      {/* New Chat Button */}
      <div className="p-3 border-b border-claude-border">
        <button
          onClick={createSession}
          className="w-full flex items-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary-hover text-white rounded-lg transition-colors font-medium"
        >
          <MessageSquarePlus size={18} />
          New Chat
        </button>
      </div>

      {/* Chat History */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-2">
          {sessions.length === 0 ? (
            <div className="text-center text-claude-text-secondary text-sm py-8">
              No conversations yet
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={cn(
                    "group relative flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors",
                    currentSessionId === session.id
                      ? "bg-claude-light text-claude-text"
                      : "text-claude-text-secondary hover:bg-claude-light/50"
                  )}
                  onClick={() => setCurrentSession(session.id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {session.title}
                    </div>
                    <div className="text-xs text-claude-text-secondary">
                      {formatTimestamp(session.updatedAt)}
                    </div>
                  </div>

                  {/* Delete Button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (
                        confirm("Are you sure you want to delete this chat?")
                      ) {
                        deleteSession(session.id);
                      }
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-claude-border rounded transition-opacity"
                    aria-label="Delete chat"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-claude-border">
        <div className="text-xs text-claude-text-secondary text-center">
          NEOS v0.8.1
        </div>
      </div>
    </aside>
  );
}
