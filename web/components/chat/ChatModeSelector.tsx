"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Brain, Database, Sparkles, SearchX } from "lucide-react";
import type { ChatMode } from "@/lib/types";
import { useRef, useEffect, KeyboardEvent } from "react";
import dynamic from "next/dynamic";

// Dynamically import SimilaritySettings for code splitting
const SimilaritySettings = dynamic(() => import("./SimilaritySettings"), {
  loading: () => <div className="text-xs text-claude-text-secondary animate-pulse">Loading...</div>,
  ssr: false,
});

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
  {
    id: "deep_research",
    name: "Deep Research",
    description: "Comprehensive multi-phase research with 100+ sources",
    icon: <SearchX className="w-4 h-4" />,
  },
];

export default function ChatModeSelector() {
  const { settings, setChatMode } = useChatStore();
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Initialize refs array
  useEffect(() => {
    buttonRefs.current = buttonRefs.current.slice(0, chatModes.length);
  }, []);

  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let nextIndex = currentIndex;

    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault();
        nextIndex = (currentIndex + 1) % chatModes.length;
        buttonRefs.current[nextIndex]?.focus();
        break;

      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        nextIndex = (currentIndex - 1 + chatModes.length) % chatModes.length;
        buttonRefs.current[nextIndex]?.focus();
        break;

      case 'Home':
        e.preventDefault();
        buttonRefs.current[0]?.focus();
        break;

      case 'End':
        e.preventDefault();
        buttonRefs.current[chatModes.length - 1]?.focus();
        break;
    }
  };

  return (
    <div
      className="flex items-center gap-3 p-2 bg-claude-dark border border-claude-border rounded-lg"
      role="toolbar"
      aria-label="Chat mode selector"
    >
      <span className="text-xs text-claude-text-secondary px-2">Mode:</span>
      <div className="flex gap-1 flex-1" role="group">
        {chatModes.map((mode, index) => (
          <button
            key={mode.id}
            ref={(el) => { buttonRefs.current[index] = el }}
            onClick={() => setChatMode(mode.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            className={`
              flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium
              transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/50
              ${
                settings.mode === mode.id
                  ? "bg-primary text-white"
                  : "bg-claude-light text-claude-text-secondary hover:bg-claude-border"
              }
            `}
            title={mode.description}
            aria-label={`${mode.name}: ${mode.description}`}
            aria-pressed={settings.mode === mode.id}
            tabIndex={settings.mode === mode.id ? 0 : -1}
          >
            {mode.icon}
            <span>{mode.name}</span>
          </button>
        ))}
      </div>

      {/* Similarity Settings - Only shows when similarity mode is active */}
      <SimilaritySettings />
    </div>
  );
}
