"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { ArrowUp, Square, AlertCircle } from "lucide-react";
import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { validateInput, createMessageRateLimiter, INPUT_CONSTANTS } from "@/lib/input-validation";

export default function InputBox() {
  const { sendMessage, isLoading, isStreaming, settings, stopGeneration } = useChatStore();
  const [input, setInput] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const rateLimiterRef = useRef(createMessageRateLimiter());

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        INPUT_CONSTANTS.MAX_TEXTAREA_HEIGHT_PX
      )}px`;
    }
  }, [input]);

  // Clear validation error when input changes
  useEffect(() => {
    if (validationError && input.trim()) {
      setValidationError(null);
    }
  }, [input, validationError]);

  const handleSubmit = async () => {
    if (!input.trim() || isLoading || isStreaming) return;

    // Validate input
    const validation = validateInput(input);
    if (!validation.isValid) {
      setValidationError(validation.error || "Invalid input");
      return;
    }

    // Check rate limit
    if (!rateLimiterRef.current.isAllowed()) {
      const timeUntilReset = rateLimiterRef.current.getTimeUntilReset();
      const secondsRemaining = Math.ceil(timeUntilReset / 1000);
      setValidationError(
        `Please wait ${secondsRemaining} second${secondsRemaining > 1 ? "s" : ""} before sending another message`
      );
      return;
    }

    const message = validation.sanitized!;
    setInput("");
    setValidationError(null);

    // sendMessage() now automatically handles streaming based on settings
    await sendMessage(message);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleStop = () => {
    console.log("[InputBox] Stop button clicked");
    stopGeneration();
  };

  const canSend = input.trim() && !isLoading && !isStreaming;
  const characterCount = input.length;
  const isNearLimit = characterCount > INPUT_CONSTANTS.MAX_MESSAGE_LENGTH * 0.9;

  return (
    <div className="border-t border-claude-border bg-claude-darker p-4">
      <div className="max-w-3xl mx-auto">
        {/* Validation Error */}
        {validationError && (
          <div className="mb-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2 text-sm text-red-400">
            <AlertCircle size={16} className="flex-shrink-0" />
            <span>{validationError}</span>
          </div>
        )}

        <div className="relative flex items-end gap-3 bg-claude-dark border border-claude-border rounded-2xl p-3 shadow-lg">
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message NEOS..."
            disabled={isLoading || isStreaming}
            aria-label="Message input"
            aria-invalid={!!validationError}
            aria-describedby={validationError ? "input-error" : undefined}
            className="flex-1 bg-transparent text-claude-text placeholder-claude-text-secondary resize-none outline-none min-h-[24px] max-h-[200px] disabled:opacity-50"
            rows={1}
          />

          {/* Send/Stop Button */}
          {isLoading || isStreaming ? (
            <button
              onClick={handleStop}
              className="flex-shrink-0 p-2 rounded-lg bg-claude-light hover:bg-claude-border transition-colors"
              title="Stop generation"
              aria-label="Stop message generation"
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
              aria-label="Send message"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>

        {/* Helper Text */}
        <div className="mt-2 flex items-center justify-between text-xs text-claude-text-secondary">
          <div className="text-center flex-1">
            NEOS can make mistakes. Consider checking important information.
            {settings.stream && (
              <span className="ml-2 text-green-400">● Streaming enabled</span>
            )}
          </div>
          {characterCount > 0 && (
            <div className={`ml-3 ${isNearLimit ? "text-yellow-400" : ""}`}>
              {characterCount.toLocaleString()} / {INPUT_CONSTANTS.MAX_MESSAGE_LENGTH.toLocaleString()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
