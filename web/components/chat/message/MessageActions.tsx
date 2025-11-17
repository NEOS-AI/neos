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
    <div className="flex items-center gap-2 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        onClick={handleCopy}
        className="p-1.5 rounded hover:bg-claude-light transition-colors"
        title="Copy message"
        aria-label="Copy message"
      >
        <Copy
          size={14}
          className={isCopied ? "text-green-400" : "text-claude-text-secondary"}
        />
      </button>

      <button
        onClick={() => onRegenerate(messageId)}
        className="p-1.5 rounded hover:bg-claude-light transition-colors"
        title="Regenerate response"
        aria-label="Regenerate response"
      >
        <RotateCw size={14} className="text-claude-text-secondary" />
      </button>

      <div className="h-4 w-px bg-claude-border mx-1" />

      <button
        onClick={() => onFeedback(messageId, "positive")}
        className={`p-1.5 rounded hover:bg-claude-light transition-colors ${
          userFeedback === "positive"
            ? "text-green-400"
            : "text-claude-text-secondary"
        }`}
        title="Good response"
        aria-label="Good response"
      >
        <ThumbsUp size={14} />
      </button>

      <button
        onClick={() => onFeedback(messageId, "negative")}
        className={`p-1.5 rounded hover:bg-claude-light transition-colors ${
          userFeedback === "negative"
            ? "text-red-400"
            : "text-claude-text-secondary"
        }`}
        title="Bad response"
        aria-label="Bad response"
      >
        <ThumbsDown size={14} />
      </button>
    </div>
  );
}
