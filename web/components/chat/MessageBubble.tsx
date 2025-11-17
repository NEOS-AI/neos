"use client";

import { Message } from "@/lib/types";
import { useChatStore } from "@/lib/stores/chat-store";
import SimilarityContextIndicator from "./SimilarityContextIndicator";
import {
  MessageAvatar,
  MessageHeader,
  MessageContent,
  MessageMetadata,
  MessageActions,
  RAGContextDetails,
} from "./message";

interface MessageBubbleProps {
  message: Message;
}

/**
 * MessageBubble Component
 * Main container for displaying a chat message
 * Refactored into smaller, focused sub-components for better maintainability
 */
export default function MessageBubble({ message }: MessageBubbleProps) {
  const { regenerateMessage, addFeedback } = useChatStore();

  const isUser = message.role === "user";
  const hasRAGContext = message.metadata?.rag_enabled || message.metadata?.rag_context;
  const hasSimilarityContext =
    message.metadata?.context_enhanced || message.metadata?.similarity_scores;

  return (
    <div className="group w-full hover:bg-claude-dark/30 transition-colors">
      <div className="max-w-3xl mx-auto px-6 py-6">
        <div className="flex gap-4 items-start">
          {/* Avatar */}
          <div className="flex-shrink-0 mt-1">
            <MessageAvatar isUser={isUser} />
          </div>

          {/* Message Content */}
          <div className="flex-1 min-w-0 pt-0.5">
            {/* Header with role and badges */}
            <MessageHeader
              isUser={isUser}
              hasRAGContext={hasRAGContext}
              hasSimilarityContext={hasSimilarityContext}
              status={message.status}
            />

            {/* Similarity Context Indicator (before content for assistant) */}
            {!isUser && hasSimilarityContext && (
              <SimilarityContextIndicator
                contextEnhanced={message.metadata?.context_enhanced || false}
                relevantMessageCount={message.metadata?.relevant_message_count || 0}
                similarityScores={message.metadata?.similarity_scores}
                searchConfig={message.metadata?.search_config}
                errors={
                  message.metadata?.similarity_search_failed
                    ? [message.metadata?.error_message]
                    : []
                }
              />
            )}

            {/* Message Content */}
            <div className="text-claude-text">
              <MessageContent
                content={message.content}
                isUser={isUser}
                isPending={message.status === "pending"}
              />
            </div>

            {/* Metadata (for assistant messages only) */}
            {!isUser && (
              <MessageMetadata
                modelName={message.model_name}
                totalTokens={message.total_tokens}
                qualityScore={message.quality_score}
                executionTime={message.metadata?.execution_time}
              />
            )}

            {/* RAG Context Details */}
            {!isUser && hasRAGContext && !hasSimilarityContext && (
              <RAGContextDetails ragContext={message.metadata?.rag_context} />
            )}

            {/* Action Buttons */}
            {!isUser && message.status === "completed" && (
              <MessageActions
                messageId={message.message_id}
                content={message.content}
                userFeedback={message.user_feedback}
                onRegenerate={regenerateMessage}
                onFeedback={addFeedback}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
