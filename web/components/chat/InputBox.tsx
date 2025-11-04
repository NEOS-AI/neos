"use client";

import { useState, useRef, KeyboardEvent } from "react";
import { useChatStore } from "@/lib/stores/chat-store";
import { Send, Loader2 } from "lucide-react";
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
    <div className="max-w-3xl mx-auto w-full p-4">
      <div className="relative bg-claude-light rounded-2xl border border-claude-border focus-within:border-primary transition-colors">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask NEOS anything..."
          disabled={isLoading}
          rows={1}
          className={cn(
            "w-full bg-transparent text-claude-text placeholder-claude-text-secondary",
            "px-4 py-3 pr-12 resize-none outline-none",
            "max-h-[200px] overflow-y-auto",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          style={{ minHeight: "48px" }}
        />

        <button
          onClick={handleSubmit}
          disabled={!input.trim() || isLoading}
          className={cn(
            "absolute right-2 bottom-2 p-2 rounded-lg transition-colors",
            "disabled:opacity-40 disabled:cursor-not-allowed",
            input.trim() && !isLoading
              ? "bg-primary hover:bg-primary-hover text-white"
              : "bg-claude-border text-claude-text-secondary"
          )}
          aria-label="Send message"
        >
          {isLoading ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <Send size={20} />
          )}
        </button>
      </div>

      <div className="mt-2 text-xs text-center text-claude-text-secondary">
        Press Enter to send, Shift+Enter for new line
      </div>
    </div>
  );
}
