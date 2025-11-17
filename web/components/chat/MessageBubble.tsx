"use client";

import { Message } from "@/lib/types";
import { useChatStore } from "@/lib/stores/chat-store";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  User,
  Clock,
  CheckCircle2,
  ThumbsUp,
  ThumbsDown,
  RotateCw,
  Edit2,
  Copy,
  Database,
  Brain,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useState } from "react";
import SimilarityContextIndicator from "./SimilarityContextIndicator";

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const { regenerateMessage, addFeedback } = useChatStore();
  const [showDetails, setShowDetails] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const isUser = message.role === "user";
  const hasRAGContext = message.metadata?.rag_enabled || message.metadata?.rag_context;
  const hasSimilarityContext =
    message.metadata?.context_enhanced || message.metadata?.similarity_scores;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  const handleFeedback = async (feedback: "positive" | "negative" | "neutral") => {
    await addFeedback(message.message_id, feedback);
  };

  const handleRegenerate = async () => {
    await regenerateMessage(message.message_id);
  };

  return (
    <div className="group w-full hover:bg-claude-dark/30 transition-colors">
      <div className="max-w-3xl mx-auto px-6 py-6">
        <div className="flex gap-4 items-start">
          {/* Avatar */}
          <div className="flex-shrink-0 mt-1">
            {isUser ? (
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
                <User size={16} className="text-white" />
              </div>
            ) : (
              <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white font-bold text-sm">
                N
              </div>
            )}
          </div>

          {/* Message Content */}
          <div className="flex-1 min-w-0 pt-0.5">
            {/* Role Label with Context Badge */}
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
              {message.status === "streaming" && (
                <div className="flex items-center gap-1 px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">
                  <span className="animate-pulse">●</span>
                  <span>Streaming</span>
                </div>
              )}
              {message.status === "pending" && (
                <div className="flex items-center gap-1 px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded text-xs">
                  <span className="animate-pulse">●</span>
                  <span>Thinking</span>
                </div>
              )}
            </div>

            {/* Similarity Context Indicator (before content for assistant) */}
            {!isUser && hasSimilarityContext && (
              <SimilarityContextIndicator
                contextEnhanced={message.metadata?.context_enhanced || false}
                relevantMessageCount={message.metadata?.relevant_message_count || 0}
                similarityScores={message.metadata?.similarity_scores}
                searchConfig={message.metadata?.search_config}
                errors={message.metadata?.similarity_search_failed ? [message.metadata?.error_message] : []}
              />
            )}

            {/* Content */}
            <div className="text-claude-text">
              {isUser ? (
                <div className="whitespace-pre-wrap text-[15px] leading-relaxed">
                  {message.content}
                </div>
              ) : message.status === "pending" && !message.content ? (
                // Show loading dots for pending assistant messages
                <div className="flex items-center gap-1 py-2">
                  <div className="w-2 h-2 bg-claude-text-secondary rounded-full animate-pulse" />
                  <div
                    className="w-2 h-2 bg-claude-text-secondary rounded-full animate-pulse"
                    style={{ animationDelay: "0.2s" }}
                  />
                  <div
                    className="w-2 h-2 bg-claude-text-secondary rounded-full animate-pulse"
                    style={{ animationDelay: "0.4s" }}
                  />
                </div>
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  className="markdown-content prose prose-invert max-w-none text-[15px]"
                  components={{
                    p: ({ children }) => (
                      <p className="mb-4 last:mb-0 leading-relaxed">{children}</p>
                    ),
                    code: ({ inline, children, ...props }: any) =>
                      inline ? (
                        <code
                          className="bg-black/40 border border-claude-border px-1.5 py-0.5 rounded text-[13px] font-mono text-orange-300"
                          {...props}
                        >
                          {children}
                        </code>
                      ) : (
                        <code
                          className="block bg-black/60 border border-claude-border p-4 rounded-lg overflow-x-auto text-[13px] leading-relaxed"
                          {...props}
                        >
                          {children}
                        </code>
                      ),
                    pre: ({ children }) => (
                      <pre className="my-4 overflow-hidden rounded-lg">{children}</pre>
                    ),
                    ul: ({ children }) => <ul className="mb-4 space-y-2">{children}</ul>,
                    ol: ({ children }) => <ol className="mb-4 space-y-2">{children}</ol>,
                    li: ({ children }) => (
                      <li className="leading-relaxed">{children}</li>
                    ),
                  }}
                >
                  {message.content || "..."}
                </ReactMarkdown>
              )}
            </div>

            {/* Basic Metadata */}
            {!isUser && (
              <div className="flex items-center gap-4 mt-3 text-xs text-claude-text-secondary">
                {message.model_name && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-orange-500">●</span>
                    <span>{message.model_name.split("-").slice(0, 2).join(" ")}</span>
                  </div>
                )}
                {message.total_tokens && (
                  <div className="flex items-center gap-1.5">
                    <span>{message.total_tokens} tokens</span>
                  </div>
                )}
                {message.quality_score && (
                  <div className="flex items-center gap-1.5">
                    <CheckCircle2 size={12} />
                    <span>{(message.quality_score * 100).toFixed(0)}%</span>
                  </div>
                )}
                {message.metadata?.execution_time && (
                  <div className="flex items-center gap-1.5">
                    <Clock size={12} />
                    <span>
                      {(message.metadata.execution_time / 1000).toFixed(2)}s
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* RAG Context Details */}
            {!isUser && hasRAGContext && !hasSimilarityContext && (
              <div className="mt-3">
                <button
                  onClick={() => setShowDetails(!showDetails)}
                  className="flex items-center gap-1 text-xs text-claude-text-secondary hover:text-claude-text transition-colors"
                >
                  {showDetails ? (
                    <ChevronUp size={14} />
                  ) : (
                    <ChevronDown size={14} />
                  )}
                  <span>
                    {showDetails ? "Hide" : "Show"} RAG context details
                  </span>
                </button>

                {showDetails && message.metadata?.rag_context && (
                  <div className="mt-2 p-3 bg-claude-light border border-claude-border rounded-lg space-y-2">
                    <div className="space-y-1">
                      <div className="text-xs font-medium text-blue-400">
                        RAG Context
                      </div>
                      <div className="text-xs text-claude-text-secondary space-y-1">
                        <div>
                          Retrieved:{" "}
                          {message.metadata.rag_context.total_retrieved || 0}{" "}
                          messages
                        </div>
                        {message.metadata.rag_context.avg_similarity && (
                          <div>
                            Avg Similarity:{" "}
                            {(
                              message.metadata.rag_context.avg_similarity * 100
                            ).toFixed(1)}
                            %
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Action Buttons */}
            {!isUser && message.status === "completed" && (
              <div className="flex items-center gap-2 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={handleCopy}
                  className="p-1.5 rounded hover:bg-claude-light transition-colors"
                  title="Copy message"
                >
                  <Copy
                    size={14}
                    className={isCopied ? "text-green-400" : "text-claude-text-secondary"}
                  />
                </button>

                <button
                  onClick={handleRegenerate}
                  className="p-1.5 rounded hover:bg-claude-light transition-colors"
                  title="Regenerate response"
                >
                  <RotateCw size={14} className="text-claude-text-secondary" />
                </button>

                <div className="h-4 w-px bg-claude-border mx-1" />

                <button
                  onClick={() => handleFeedback("positive")}
                  className={`p-1.5 rounded hover:bg-claude-light transition-colors ${
                    message.user_feedback === "positive"
                      ? "text-green-400"
                      : "text-claude-text-secondary"
                  }`}
                  title="Good response"
                >
                  <ThumbsUp size={14} />
                </button>

                <button
                  onClick={() => handleFeedback("negative")}
                  className={`p-1.5 rounded hover:bg-claude-light transition-colors ${
                    message.user_feedback === "negative"
                      ? "text-red-400"
                      : "text-claude-text-secondary"
                  }`}
                  title="Bad response"
                >
                  <ThumbsDown size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
