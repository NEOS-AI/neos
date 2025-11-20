"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { ArrowUp, Square, AlertCircle } from "lucide-react";
import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { validateInput, createMessageRateLimiter, INPUT_CONSTANTS } from "@/lib/input-validation";
import { createLogger } from "@/lib/logger";

const logger = createLogger("InputBox");

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
    logger.debug("Stop button clicked");
    stopGeneration();
  };

  const canSend = input.trim() && !isLoading && !isStreaming;
  const characterCount = input.length;
  const isNearLimit = characterCount > INPUT_CONSTANTS.MAX_MESSAGE_LENGTH * 0.9;

  return (
    <div className="sticky bottom-0 bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl border-t border-gray-200/50 dark:border-gray-800/50 px-4 py-4 sm:px-6">
      <div className="max-w-4xl mx-auto">
        {/* Validation Error */}
        {validationError && (
          <div className="mb-3 p-3 bg-gradient-to-r from-red-50 to-red-100/80 dark:from-red-900/20 dark:to-red-800/20 border border-red-200 dark:border-red-800/50 rounded-2xl flex items-center gap-3 text-sm text-red-700 dark:text-red-400 animate-fade-in-down shadow-sm">
            <AlertCircle size={18} className="flex-shrink-0" />
            <span>{validationError}</span>
          </div>
        )}

        <div className="relative flex items-end gap-2 sm:gap-3 bg-gradient-to-br from-white to-gray-50/50 dark:from-gray-800 dark:to-gray-800/80 border-2 border-gray-300/60 dark:border-gray-700/60 rounded-3xl p-3 shadow-lg hover:shadow-2xl focus-within:border-blue-500 dark:focus-within:border-blue-400 focus-within:shadow-blue-500/20 dark:focus-within:shadow-blue-400/20 transition-all duration-300">
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
            className="flex-1 bg-transparent text-gray-900 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400 resize-none outline-none min-h-[24px] max-h-[200px] disabled:opacity-50 text-base leading-relaxed px-1"
            rows={1}
          />

          {/* Send/Stop Button */}
          {isLoading || isStreaming ? (
            <button
              onClick={handleStop}
              className="flex-shrink-0 p-2.5 rounded-full bg-gradient-to-br from-gray-200 to-gray-300 dark:from-gray-700 dark:to-gray-600 hover:from-gray-300 hover:to-gray-400 dark:hover:from-gray-600 dark:hover:to-gray-500 transition-all duration-300 hover:scale-110 active:scale-95 shadow-md hover:shadow-lg"
              title="Stop generation"
              aria-label="Stop message generation"
            >
              <Square size={20} className="text-gray-700 dark:text-gray-300" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              className={`
                flex-shrink-0 p-2.5 rounded-full transition-all duration-300 relative overflow-hidden
                ${
                  canSend
                    ? "bg-gradient-to-br from-blue-600 via-blue-500 to-purple-600 hover:from-blue-700 hover:via-blue-600 hover:to-purple-700 text-white shadow-lg hover:shadow-xl hover:shadow-blue-500/50 dark:hover:shadow-blue-400/30 hover:scale-110 active:scale-95"
                    : "bg-gray-200 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed opacity-50"
                }
              `}
              title="Send message"
              aria-label="Send message"
            >
              <ArrowUp size={20} className="font-bold relative z-10" />
            </button>
          )}
        </div>

        {/* Helper Text */}
        <div className="mt-3 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 px-2">
          <div className="flex items-center gap-3">
            <span>NEOS can make mistakes. Consider checking important information.</span>
            {settings.stream && (
              <span className="flex items-center gap-1.5 text-green-600 dark:text-green-400">
                <span className="w-1.5 h-1.5 bg-green-600 dark:bg-green-400 rounded-full animate-pulse" />
                Streaming
              </span>
            )}
          </div>
          {characterCount > 0 && (
            <div className={`ml-3 font-mono ${isNearLimit ? "text-yellow-600 dark:text-yellow-400 font-semibold" : ""}`}>
              {characterCount.toLocaleString()} / {INPUT_CONSTANTS.MAX_MESSAGE_LENGTH.toLocaleString()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
