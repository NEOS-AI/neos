import { Clock, CheckCircle2 } from "lucide-react";

interface MessageMetadataProps {
  modelName?: string;
  totalTokens?: number;
  qualityScore?: number;
  executionTime?: number;
}

/**
 * MessageMetadata Component
 * Displays message metadata (model, tokens, quality score, execution time)
 */
export default function MessageMetadata({
  modelName,
  totalTokens,
  qualityScore,
  executionTime,
}: MessageMetadataProps) {
  // Don't render if no metadata
  if (!modelName && !totalTokens && !qualityScore && !executionTime) {
    return null;
  }

  return (
    <div className="flex items-center gap-4 mt-3 text-xs text-claude-text-secondary">
      {modelName && (
        <div className="flex items-center gap-1.5">
          <span className="text-orange-500">●</span>
          <span>{modelName.split("-").slice(0, 2).join(" ")}</span>
        </div>
      )}

      {totalTokens && (
        <div className="flex items-center gap-1.5">
          <span>{totalTokens} tokens</span>
        </div>
      )}

      {qualityScore && (
        <div className="flex items-center gap-1.5">
          <CheckCircle2 size={12} />
          <span>{(qualityScore * 100).toFixed(0)}%</span>
        </div>
      )}

      {executionTime && (
        <div className="flex items-center gap-1.5">
          <Clock size={12} />
          <span>{(executionTime / 1000).toFixed(2)}s</span>
        </div>
      )}
    </div>
  );
}
