"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { Plus, Send, AlertCircle } from "lucide-react";
import { validateInput, INPUT_CONSTANTS } from "@/lib/input-validation";

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
  const [validationError, setValidationError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const newHeight = Math.min(textarea.scrollHeight, INPUT_CONSTANTS.MAX_TEXTAREA_HEIGHT_PX);
      textarea.style.height = `${newHeight}px`;
    }
  }, [message]);

  // Clear validation error when message changes
  useEffect(() => {
    if (validationError && message.trim()) {
      setValidationError(null);
    }
  }, [message, validationError]);

  const handleSubmit = () => {
    if (!message.trim() || disabled) return;

    // Validate input
    const validation = validateInput(message);
    if (!validation.isValid) {
      setValidationError(validation.error || "Invalid input");
      return;
    }

    const sanitizedMessage = validation.sanitized!;
    onSend(sanitizedMessage);
    setMessage("");
    setValidationError(null);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const characterCount = message.length;
  const isNearLimit = characterCount > INPUT_CONSTANTS.MAX_MESSAGE_LENGTH * 0.9;

  return (
    <div className="w-full max-w-3xl mx-auto">
      {/* Validation Error */}
      {validationError && (
        <div className="mb-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2 text-sm text-red-400">
          <AlertCircle size={16} className="flex-shrink-0" />
          <span>{validationError}</span>
        </div>
      )}

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
          aria-invalid={!!validationError}
          aria-describedby={validationError ? "composer-error" : undefined}
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

      {/* Hint text and character count */}
      <div className="mt-2 flex items-center justify-between text-text-muted text-xs">
        <div className="text-center flex-1">
          Press <kbd className="px-1.5 py-0.5 rounded bg-chip-bg border border-chip-line">Cmd</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-chip-bg border border-chip-line">Enter</kbd> to send
        </div>
        {characterCount > 0 && (
          <div className={`ml-3 ${isNearLimit ? "text-yellow-400" : ""}`}>
            {characterCount.toLocaleString()} / {INPUT_CONSTANTS.MAX_MESSAGE_LENGTH.toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
}
