"use client";

import { memo } from "react";
import dynamic from "next/dynamic";
import { Message } from "@/lib/types";
import { useChatStore } from "@/lib/stores/chat-store";
import {
  MessageAvatar,
  MessageHeader,
  MessageContent,
  MessageMetadata,
} from "./message";

// Dynamically import less frequently used components
const SimilarityContextIndicator = dynamic(() => import("./SimilarityContextIndicator"), {
  ssr: false,
});
const MessageActions = dynamic(() => import("./message/MessageActions"), {
  ssr: false,
});
const RAGContextDetails = dynamic(() => import("./message/RAGContextDetails"), {
  ssr: false,
});

interface MessageBubbleProps {
  message: Message;
}

/**
 * MessageBubble Component
 * Modern chat UI with ChatGPT/Claude-style design
 * User messages: right-aligned with gradient background
 * AI messages: left-aligned with subtle background
 *
 * Performance: Memoized to prevent unnecessary re-renders in long conversations
 */
function MessageBubbleComponent({ message }: MessageBubbleProps) {
  const { regenerateMessage, addFeedback } = useChatStore();

  const isUser = message.role === "user";
  const hasRAGContext = message.metadata?.rag_enabled || message.metadata?.rag_context;
  const hasSimilarityContext =
    message.metadata?.context_enhanced || message.metadata?.similarity_scores;

  return (
    <div
      role="article"
      aria-label={`${isUser ? 'Your message' : 'Assistant message'}${message.status === 'streaming' ? ', streaming' : ''}`}
      className={`
        group w-full py-6 px-4 sm:px-6
        transition-all duration-500 ease-out
        ${isUser
          ? 'bg-transparent'
          : 'bg-gradient-to-b from-transparent via-gray-50/40 to-transparent dark:via-gray-800/30 hover:via-gray-100/60 dark:hover:via-gray-700/40'
        }
        animate-fade-in-up
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
                transition-all duration-300
                ${isUser
                  ? 'bg-gradient-to-br from-blue-600 via-blue-500 to-purple-600 text-white rounded-3xl rounded-tr-md px-5 py-3.5 max-w-[85%] shadow-lg hover:shadow-xl hover:scale-[1.02] transform'
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

/**
 * Memoized MessageBubble to prevent re-renders when message hasn't changed
 * This significantly improves performance in long conversations (50+ messages)
 */
export default memo(MessageBubbleComponent, (prevProps, nextProps) => {
  // Only re-render if message content, status, or metadata has changed
  return (
    prevProps.message.message_id === nextProps.message.message_id &&
    prevProps.message.content === nextProps.message.content &&
    prevProps.message.status === nextProps.message.status &&
    prevProps.message.user_feedback === nextProps.message.user_feedback &&
    JSON.stringify(prevProps.message.metadata) === JSON.stringify(nextProps.message.metadata)
  );
});
