"use client";

import { useState, useRef, KeyboardEvent } from "react";
import { useChatStore } from "@/lib/stores/chat-store";
import { ArrowUp, StopCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export default function InputBox() {
  const [input, setInput] = useState("");
  const { sendMessage, isLoading } = useChatStore();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = async () => {
    if (!input.trim() || isLoading) return;

    const message = input.trim();
    setInput("");

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    await sendMessage(message);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);

    // Auto-resize textarea
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
  };

  return (
    <div className="border-t border-claude-border bg-claude-darker">
      <div className="max-w-3xl mx-auto w-full px-6 py-6">
        <div className="relative">
          {/* Input Container */}
          <div className={cn(
            "relative rounded-2xl border transition-all duration-200",
            "bg-claude-dark/60",
            input.trim()
              ? "border-claude-text-secondary shadow-lg shadow-black/20"
              : "border-claude-border"
          )}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder="Message NEOS..."
              disabled={isLoading}
              rows={1}
              className={cn(
                "w-full bg-transparent text-claude-text placeholder-claude-text-secondary/70",
                "px-5 py-4 pr-14 resize-none outline-none",
                "text-[15px] leading-relaxed",
                "max-h-[200px] overflow-y-auto",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              style={{ minHeight: "52px" }}
            />

            {/* Send/Stop Button */}
            <div className="absolute right-3 bottom-3">
              {isLoading ? (
                <button
                  onClick={() => {/* TODO: Implement stop */}}
                  className="w-8 h-8 rounded-lg bg-claude-text-secondary/20 hover:bg-claude-text-secondary/30 flex items-center justify-center transition-colors"
                  aria-label="Stop generating"
                >
                  <StopCircle size={18} className="text-claude-text" />
                </button>
              ) : (
                <button
                  onClick={handleSubmit}
                  disabled={!input.trim()}
                  className={cn(
                    "w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200",
                    input.trim()
                      ? "bg-claude-text text-claude-darker hover:bg-white"
                      : "bg-claude-border/40 text-claude-text-secondary cursor-not-allowed"
                  )}
                  aria-label="Send message"
                >
                  <ArrowUp size={18} strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>

          {/* Helper Text */}
          <div className="mt-3 text-xs text-center text-claude-text-secondary/80">
            NEOS can make mistakes. Consider checking important information.
          </div>
        </div>
      </div>
    </div>
  );
}
