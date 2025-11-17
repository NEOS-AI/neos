import { Copy, RotateCw, ThumbsUp, ThumbsDown } from "lucide-react";
import { useState } from "react";

interface MessageActionsProps {
  messageId: string;
  content: string;
  userFeedback?: "positive" | "negative" | "neutral";
  onRegenerate: (messageId: string) => Promise<void>;
  onFeedback: (messageId: string, feedback: "positive" | "negative" | "neutral") => Promise<void>;
}

/**
 * MessageActions Component
 * Displays action buttons for copying, regenerating, and providing feedback
 */
export default function MessageActions({
  messageId,
  content,
  userFeedback,
  onRegenerate,
  onFeedback,
}: MessageActionsProps) {
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  return (
    <div className="flex items-center gap-1 mt-3 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
      <button
        onClick={handleCopy}
        className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-all duration-200 hover:scale-105 active:scale-95"
        title="Copy message"
        aria-label="Copy message"
      >
        <Copy
          size={16}
          className={isCopied ? "text-green-600 dark:text-green-400" : "text-gray-600 dark:text-gray-400"}
        />
      </button>

      <button
        onClick={() => onRegenerate(messageId)}
        className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-all duration-200 hover:scale-105 active:scale-95"
        title="Regenerate response"
        aria-label="Regenerate response"
      >
        <RotateCw size={16} className="text-gray-600 dark:text-gray-400" />
      </button>

      <div className="h-5 w-px bg-gray-300 dark:bg-gray-700 mx-1" />

      <button
        onClick={() => onFeedback(messageId, "positive")}
        className={`p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-all duration-200 hover:scale-105 active:scale-95 ${
          userFeedback === "positive"
            ? "text-green-600 dark:text-green-400 bg-green-500/10"
            : "text-gray-600 dark:text-gray-400"
        }`}
        title="Good response"
        aria-label="Good response"
      >
        <ThumbsUp size={16} />
      </button>

      <button
        onClick={() => onFeedback(messageId, "negative")}
        className={`p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-all duration-200 hover:scale-105 active:scale-95 ${
          userFeedback === "negative"
            ? "text-red-600 dark:text-red-400 bg-red-500/10"
            : "text-gray-600 dark:text-gray-400"
        }`}
        title="Bad response"
        aria-label="Bad response"
      >
        <ThumbsDown size={16} />
      </button>
    </div>
  );
}
