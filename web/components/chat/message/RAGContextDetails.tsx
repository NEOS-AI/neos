import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

interface RAGContext {
  total_retrieved?: number;
  avg_similarity?: number;
}

interface RAGContextDetailsProps {
  ragContext?: RAGContext;
}

/**
 * RAGContextDetails Component
 * Displays expandable RAG context information
 */
export default function RAGContextDetails({ ragContext }: RAGContextDetailsProps) {
  const [showDetails, setShowDetails] = useState(false);

  if (!ragContext) {
    return null;
  }

  return (
    <div className="mt-3">
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="flex items-center gap-1 text-xs text-claude-text-secondary hover:text-claude-text transition-colors"
        aria-expanded={showDetails}
        aria-label={showDetails ? "Hide RAG context details" : "Show RAG context details"}
      >
        {showDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        <span>{showDetails ? "Hide" : "Show"} RAG context details</span>
      </button>

      {showDetails && (
        <div className="mt-2 p-3 bg-claude-light border border-claude-border rounded-lg space-y-2">
          <div className="space-y-1">
            <div className="text-xs font-medium text-blue-400">RAG Context</div>
            <div className="text-xs text-claude-text-secondary space-y-1">
              <div>Retrieved: {ragContext.total_retrieved || 0} messages</div>
              {ragContext.avg_similarity && (
                <div>
                  Avg Similarity: {(ragContext.avg_similarity * 100).toFixed(1)}%
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
