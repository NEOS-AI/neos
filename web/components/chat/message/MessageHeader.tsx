import { Database, Brain } from "lucide-react";

interface MessageHeaderProps {
  isUser: boolean;
  hasRAGContext: boolean;
  hasSimilarityContext: boolean;
  status?: string;
}

/**
 * MessageHeader Component
 * Displays the role label and context badges
 */
export default function MessageHeader({
  isUser,
  hasRAGContext,
  hasSimilarityContext,
  status,
}: MessageHeaderProps) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        {isUser ? "You" : "NEOS"}
      </div>

      {hasRAGContext && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-full text-xs font-medium border border-blue-500/20">
          <Database size={12} />
          <span>RAG</span>
        </div>
      )}

      {hasSimilarityContext && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-purple-500/10 text-purple-600 dark:text-purple-400 rounded-full text-xs font-medium border border-purple-500/20">
          <Brain size={12} />
          <span>Similarity</span>
        </div>
      )}

      {status === "streaming" && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-green-500/10 text-green-600 dark:text-green-400 rounded-full text-xs font-medium border border-green-500/20">
          <span className="animate-pulse">●</span>
          <span>Streaming</span>
        </div>
      )}

      {status === "pending" && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded-full text-xs font-medium border border-amber-500/20">
          <span className="animate-pulse">●</span>
          <span>Thinking</span>
        </div>
      )}
    </div>
  );
}
