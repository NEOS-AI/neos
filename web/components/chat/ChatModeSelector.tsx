"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Brain, Database, Sparkles } from "lucide-react";
import type { ChatMode } from "@/lib/types";

const chatModes: Array<{
  id: ChatMode;
  name: string;
  description: string;
  icon: React.ReactNode;
}> = [
  {
    id: "standard",
    name: "Standard",
    description: "Basic conversation mode",
    icon: <Sparkles className="w-4 h-4" />,
  },
  {
    id: "rag",
    name: "RAG",
    description: "Retrieval-augmented generation with context",
    icon: <Database className="w-4 h-4" />,
  },
  {
    id: "similarity",
    name: "Similarity",
    description: "Context-aware responses using similar messages",
    icon: <Brain className="w-4 h-4" />,
  },
];

export default function ChatModeSelector() {
  const { settings, setChatMode } = useChatStore();

  return (
    <div className="flex items-center gap-2 p-2 bg-claude-dark border border-claude-border rounded-lg">
      <span className="text-xs text-claude-text-secondary px-2">Mode:</span>
      <div className="flex gap-1">
        {chatModes.map((mode) => (
          <button
            key={mode.id}
            onClick={() => setChatMode(mode.id)}
            className={`
              flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium
              transition-all duration-200
              ${
                settings.mode === mode.id
                  ? "bg-primary text-white"
                  : "bg-claude-light text-claude-text-secondary hover:bg-claude-border"
              }
            `}
            title={mode.description}
          >
            {mode.icon}
            <span>{mode.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
