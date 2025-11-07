"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { ArrowUp, Square } from "lucide-react";
import { useState, useRef, useEffect, KeyboardEvent } from "react";

export default function InputBox() {
  const { sendMessage, sendStreamingMessage, isLoading, isStreaming, settings } =
    useChatStore();
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  }, [input]);

  const handleSubmit = async () => {
    if (!input.trim() || isLoading || isStreaming) return;

    const message = input.trim();
    setInput("");

    // Use streaming or regular send based on settings
    if (settings.stream) {
      await sendStreamingMessage(message);
    } else {
      await sendMessage(message);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleStop = () => {
    // TODO: Implement stop functionality
    console.log("Stop generation");
  };

  const canSend = input.trim() && !isLoading && !isStreaming;

  return (
    <div className="border-t border-claude-border bg-claude-darker p-4">
      <div className="max-w-3xl mx-auto">
        <div className="relative flex items-end gap-3 bg-claude-dark border border-claude-border rounded-2xl p-3 shadow-lg">
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message NEOS..."
            disabled={isLoading || isStreaming}
            className="flex-1 bg-transparent text-claude-text placeholder-claude-text-secondary resize-none outline-none min-h-[24px] max-h-[200px] disabled:opacity-50"
            rows={1}
          />

          {/* Send/Stop Button */}
          {isLoading || isStreaming ? (
            <button
              onClick={handleStop}
              className="flex-shrink-0 p-2 rounded-lg bg-claude-light hover:bg-claude-border transition-colors"
              title="Stop generation"
            >
              <Square size={18} className="text-claude-text" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              className={`
                flex-shrink-0 p-2 rounded-lg transition-colors
                ${
                  canSend
                    ? "bg-primary hover:bg-primary-hover text-white"
                    : "bg-claude-light text-claude-text-secondary cursor-not-allowed"
                }
              `}
              title="Send message"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>

        {/* Helper Text */}
        <div className="mt-2 text-xs text-claude-text-secondary text-center">
          NEOS can make mistakes. Consider checking important information.
          {settings.stream && (
            <span className="ml-2 text-green-400">● Streaming enabled</span>
          )}
        </div>
      </div>
    </div>
  );
}
