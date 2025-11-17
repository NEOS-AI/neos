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
 * Modern chat UI with ChatGPT/Claude-style design
 * User messages: right-aligned with gradient background
 * AI messages: left-aligned with subtle background
 */
export default function MessageBubble({ message }: MessageBubbleProps) {
  const { regenerateMessage, addFeedback } = useChatStore();

  const isUser = message.role === "user";
  const hasRAGContext = message.metadata?.rag_enabled || message.metadata?.rag_context;
  const hasSimilarityContext =
    message.metadata?.context_enhanced || message.metadata?.similarity_scores;

  return (
    <div
      className={`
        group w-full py-6 px-4 sm:px-6
        transition-all duration-300 ease-out
        ${isUser
          ? 'bg-transparent'
          : 'bg-gradient-to-b from-transparent via-gray-50/30 to-transparent dark:via-gray-800/20 hover:via-gray-50/50 dark:hover:via-gray-800/30'
        }
        animate-fadeIn
      `}
    >
      <div className="max-w-4xl mx-auto">
        <div className={`flex gap-3 sm:gap-4 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
          {/* Avatar */}
          <div className="flex-shrink-0">
            <MessageAvatar isUser={isUser} />
          </div>

          {/* Message Content Container */}
          <div className={`flex-1 min-w-0 space-y-2 ${isUser ? 'flex flex-col items-end' : ''}`}>
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
            <div className={isUser ? 'w-full flex justify-end' : 'w-full'}>
              <div className={`
                ${isUser
                  ? 'bg-gradient-to-br from-blue-600 to-purple-600 text-white rounded-3xl rounded-tr-md px-4 py-3 max-w-[85%] shadow-md'
                  : 'text-gray-900 dark:text-gray-100'
                }
              `}>
                <MessageContent
                  content={message.content}
                  isUser={isUser}
                  isPending={message.status === "pending"}
                />
              </div>
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
