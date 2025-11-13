"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { Plus, Send } from "lucide-react";

interface ChatComposerProps {
  onSend: (message: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

export default function ChatComposer({
  onSend,
  placeholder = "What can I help you with?",
  disabled = false
}: ChatComposerProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const newHeight = Math.min(textarea.scrollHeight, 160); // Max 4 lines (~40px per line)
      textarea.style.height = `${newHeight}px`;
    }
  }, [message]);

  const handleSubmit = () => {
    if (message.trim() && !disabled) {
      onSend(message.trim());
      setMessage("");
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto">
      <div
        className="
          relative flex items-end gap-3
          bg-bg-surface border border-line-soft rounded-3xl
          p-4
          transition-all duration-200
          focus-within:ring-2 focus-within:ring-brand-accent/50 focus-within:border-brand-accent/50
          hover:border-line-soft/80
        "
      >
        {/* Attachment button */}
        <button
          className="
            flex-shrink-0 p-2 rounded-xl
            text-text-secondary hover:text-text-primary hover:bg-action-hover
            transition-colors
            disabled:opacity-50 disabled:cursor-not-allowed
          "
          title="Attach files"
          disabled={disabled}
          aria-label="Attach files"
        >
          <Plus className="w-5 h-5" />
        </button>

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="
            flex-1 bg-transparent border-none outline-none resize-none
            text-text-primary placeholder:text-text-muted
            text-body-m
            disabled:opacity-50 disabled:cursor-not-allowed
            min-h-[40px] max-h-[160px]
          "
          aria-label="Message input"
        />

        {/* Send button */}
        <button
          onClick={handleSubmit}
          disabled={!message.trim() || disabled}
          className="
            flex-shrink-0 p-2 rounded-xl
            text-text-secondary hover:text-brand-accent hover:bg-action-hover
            transition-colors
            disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-text-secondary disabled:hover:bg-transparent
          "
          title="Send message (Cmd/Ctrl + Enter)"
          aria-label="Send message"
        >
          <Send className="w-5 h-5" />
        </button>
      </div>

      {/* Hint text */}
      <div className="mt-2 text-center text-text-muted text-xs">
        Press <kbd className="px-1.5 py-0.5 rounded bg-chip-bg border border-chip-line">Cmd</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-chip-bg border border-chip-line">Enter</kbd> to send
      </div>
    </div>
  );
}
