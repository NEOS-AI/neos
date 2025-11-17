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
      <div className="text-sm font-semibold text-claude-text">
        {isUser ? "You" : "NEOS"}
      </div>

      {hasRAGContext && (
        <div className="flex items-center gap-1 px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">
          <Database size={10} />
          <span>RAG</span>
        </div>
      )}

      {hasSimilarityContext && (
        <div className="flex items-center gap-1 px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded text-xs">
          <Brain size={10} />
          <span>Similarity</span>
        </div>
      )}

      {status === "streaming" && (
        <div className="flex items-center gap-1 px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">
          <span className="animate-pulse">●</span>
          <span>Streaming</span>
        </div>
      )}

      {status === "pending" && (
        <div className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded text-xs">
          <span className="animate-pulse">●</span>
          <span>Thinking</span>
        </div>
      )}
    </div>
  );
}
