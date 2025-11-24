"use client";

import { Brain, ExternalLink, AlertCircle } from "lucide-react";
import { useState } from "react";

interface SimilarityScore {
  message_id: string;
  similarity_score: number;
  search_type?: string;
}

interface SimilarityContextIndicatorProps {
  contextEnhanced: boolean;
  relevantMessageCount: number;
  similarityScores?: SimilarityScore[];
  searchConfig?: {
    top_k: number;
    threshold: number;
    include_cross_conversation: boolean;
  };
  errors?: string[];
}

export default function SimilarityContextIndicator({
  contextEnhanced,
  relevantMessageCount,
  similarityScores = [],
  searchConfig,
  errors = [],
}: SimilarityContextIndicatorProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Don't show if no context was used and no errors
  if (!contextEnhanced && errors.length === 0) {
    return null;
  }

  // Show error state
  if (errors.length > 0) {
    return (
      <div className="flex items-start gap-2 p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg text-xs">
        <AlertCircle className="w-4 h-4 text-yellow-500 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          <p className="font-medium text-yellow-600 dark:text-yellow-400">
            Similarity Search Warning
          </p>
          {errors.map((error, idx) => (
            <p key={idx} className="text-yellow-600/80 dark:text-yellow-400/80 mt-1">
              {error}
            </p>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-3">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 w-full p-3 bg-primary/10 border border-primary/30 rounded-lg text-xs hover:bg-primary/15 transition-colors"
      >
        <Brain className="w-4 h-4 text-primary flex-shrink-0" />
        <div className="flex-1 text-left">
          <span className="font-medium text-primary">
            Context Enhanced
          </span>
          <span className="text-claude-text-secondary ml-2">
            ({relevantMessageCount} similar {relevantMessageCount === 1 ? "message" : "messages"} found)
          </span>
        </div>
        <span className="text-claude-text-tertiary">
          {isExpanded ? "▼" : "▶"}
        </span>
      </button>

      {isExpanded && (
        <div className="mt-2 p-3 bg-claude-light border border-claude-border rounded-lg space-y-3">
          {/* Search Configuration */}
          {searchConfig && (
            <div className="pb-3 border-b border-claude-border">
              <h4 className="text-xs font-semibold text-claude-text-primary mb-2">
                Search Configuration
              </h4>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-claude-text-secondary">Top K:</span>
                  <span className="ml-2 font-medium text-claude-text-primary">
                    {searchConfig.top_k}
                  </span>
                </div>
                <div>
                  <span className="text-claude-text-secondary">Threshold:</span>
                  <span className="ml-2 font-medium text-claude-text-primary">
                    {searchConfig.threshold.toFixed(2)}
                  </span>
                </div>
                <div className="col-span-2">
                  <span className="text-claude-text-secondary">
                    Cross-Conversation:
                  </span>
                  <span className="ml-2 font-medium text-claude-text-primary">
                    {searchConfig.include_cross_conversation ? "Enabled" : "Disabled"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Similarity Scores */}
          {similarityScores.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-claude-text-primary mb-2">
                Similar Messages Used
              </h4>
              <div className="space-y-2">
                {similarityScores.map((score, idx) => (
                  <div
                    key={score.message_id}
                    className="flex items-center gap-3 p-2 bg-claude-dark rounded border border-claude-border"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-claude-text-primary">
                          Message #{idx + 1}
                        </span>
                        {score.search_type === "cross_conversation" && (
                          <span className="px-1.5 py-0.5 bg-primary/20 text-primary text-xs rounded">
                            Cross-Conv
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-claude-text-tertiary mt-0.5">
                        ID: {score.message_id.slice(0, 8)}...
                      </div>
                    </div>

                    {/* Similarity Score Bar */}
                    <div className="flex items-center gap-2 w-32">
                      <div className="flex-1 h-2 bg-claude-border rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-blue-500 to-primary transition-all"
                          style={{
                            width: `${score.similarity_score * 100}%`,
                          }}
                        />
                      </div>
                      <span className="text-xs font-semibold text-primary w-10 text-right">
                        {(score.similarity_score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stats Summary */}
          <div className="pt-3 border-t border-claude-border">
            <div className="flex items-center justify-between text-xs">
              <span className="text-claude-text-secondary">
                Average Similarity:
              </span>
              <span className="font-semibold text-primary">
                {similarityScores.length > 0
                  ? (
                      (similarityScores.reduce(
                        (sum, s) => sum + s.similarity_score,
                        0
                      ) /
                        similarityScores.length) *
                      100
                    ).toFixed(1)
                  : 0}
                %
              </span>
            </div>
            <div className="flex items-center justify-between text-xs mt-1">
              <span className="text-claude-text-secondary">
                Context Quality:
              </span>
              <span className="font-semibold text-primary">
                {similarityScores.length > 0 &&
                similarityScores[0].similarity_score >= 0.85
                  ? "Excellent"
                  : similarityScores.length > 0 &&
                    similarityScores[0].similarity_score >= 0.75
                  ? "Good"
                  : "Fair"}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
