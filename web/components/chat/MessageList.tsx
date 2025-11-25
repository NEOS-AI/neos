"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import MessageBubble from "./MessageBubble";
import { useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Sparkles, Database, Brain, ArrowRight } from "lucide-react";
import { PERFORMANCE, UI_DIMENSIONS } from "@/lib/constants";
import { createLogger } from "@/lib/logger";

const logger = createLogger("MessageList");

const examplePrompts = [
  {
    icon: <Sparkles className="w-4 h-4" />,
    title: "Deep Research",
    prompt: "Research the latest developments in AI safety",
  },
  {
    icon: <Database className="w-4 h-4" />,
    title: "Data Analysis",
    prompt: "Analyze trends in renewable energy adoption",
  },
  {
    icon: <Brain className="w-4 h-4" />,
    title: "RAG Query",
    prompt: "Find relevant information from my previous conversations",
  },
  {
    icon: <ArrowRight className="w-4 h-4" />,
    title: "Comparative Analysis",
    prompt: "Compare different machine learning frameworks",
  },
];

export default function MessageList() {
  // Optimized selectors with shallow comparison
  const sendMessage = useChatStore((state) => state.sendMessage);
  const settings = useChatStore((state) => state.settings);

  // Memoized selector to prevent unnecessary re-renders
  // Only re-subscribe when currentConversationId or conversations array changes
  const currentConversationId = useChatStore((state) => state.currentConversationId);
  const messages = useChatStore((state) => {
    const current = state.conversations.find(
      (c) => c.conversation_id === state.currentConversationId
    );
    return current?.messages || [];
  });

  // Get conversation for metadata only when needed
  const currentConversation = useChatStore((state) =>
    state.conversations.find(c => c.conversation_id === state.currentConversationId) || null
  );
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Only use virtualization for long message lists
  const shouldVirtualize = messages.length > PERFORMANCE.VIRTUALIZATION_THRESHOLD;

  // Setup virtualizer for long lists
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => UI_DIMENSIONS.MESSAGE_ESTIMATED_HEIGHT_PX,
    overscan: PERFORMANCE.VIRTUALIZATION_OVERSCAN,
    enabled: shouldVirtualize,
  });

  // Debug logging (only in development)
  useEffect(() => {
    logger.debug("Component rendered", {
      messagesCount: messages.length,
      conversationId: currentConversation?.conversation_id,
      hasConversation: !!currentConversation,
    });
  }, [messages, currentConversation]);

  useEffect(() => {
    logger.debug("Messages array changed", {
      count: messages.length,
      messagesSummary: messages.map(m => ({
        id: m.message_id.slice(0, 8),
        role: m.role,
        contentPreview: m.content.slice(0, 30)
      }))
    });
  }, [messages]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleExampleClick = (prompt: string) => {
    sendMessage(prompt);
  };

  return (
    <div
      ref={scrollContainerRef}
      className="h-full overflow-y-auto"
      role="log"
      aria-live="polite"
      aria-label="Chat messages"
    >
      {!currentConversation || messages.length === 0 ? (
        /* Empty State - No conversation or no messages */
        <div className="flex items-center justify-center min-h-full p-8 animate-fade-in">
          <div className="max-w-2xl text-center space-y-8">
            {/* Logo and Welcome */}
            <div className="space-y-4 animate-scale-in">
              <div className="inline-flex items-center justify-center w-20 h-20 rounded-3xl bg-gradient-to-br from-blue-700 via-slate-800 to-indigo-800 text-white text-4xl font-bold shadow-2xl shadow-blue-700/30 hover:shadow-blue-700/50 transition-all duration-300 hover:scale-110 animate-bounce-subtle">
                N
              </div>
              <h1 className="text-4xl font-bold text-claude-text bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 dark:from-slate-100 dark:via-slate-200 dark:to-slate-100 bg-clip-text text-transparent">
                Welcome to NEOS
              </h1>
              <p className="text-claude-text-secondary text-lg font-medium">
                Your intelligent search and analysis agent
              </p>
            </div>

            {/* Current Mode Info */}
            <div className="inline-flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-slate-900/5 to-slate-800/10 dark:from-slate-100/10 dark:to-slate-200/5 border border-slate-200 dark:border-claude-border rounded-2xl backdrop-blur-sm shadow-md hover:shadow-lg transition-all duration-300 hover:scale-105 animate-fade-in-up">
              {settings.mode === "rag" && (
                <>
                  <Database className="w-5 h-5 text-blue-500 dark:text-blue-400" />
                  <span className="text-sm font-medium text-slate-800 dark:text-claude-text">
                    RAG Mode - Context-aware responses
                  </span>
                </>
              )}
              {settings.mode === "similarity" && (
                <>
                  <Brain className="w-5 h-5 text-purple-500 dark:text-purple-400" />
                  <span className="text-sm font-medium text-slate-800 dark:text-claude-text">
                    Similarity Mode - Intelligent context retrieval
                  </span>
                </>
              )}
              {settings.mode === "standard" && (
                <>
                  <Sparkles className="w-5 h-5 text-blue-500 dark:text-blue-400" />
                  <span className="text-sm font-medium text-slate-800 dark:text-claude-text">
                    Standard Mode - Direct conversation
                  </span>
                </>
              )}
            </div>

            {/* Example Prompts */}
            <div className="space-y-4 animate-fade-in-up">
              <p className="text-sm font-semibold text-slate-700 dark:text-claude-text-secondary">
                Try one of these examples:
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {examplePrompts.map((example, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleExampleClick(example.prompt)}
                    className="flex items-center gap-3 p-5 bg-gradient-to-br from-white to-slate-50/50 dark:from-claude-dark dark:to-claude-light/50 border-2 border-slate-200 dark:border-claude-border rounded-2xl hover:border-primary/50 dark:hover:border-primary/50 hover:shadow-lg hover:scale-[1.02] transition-all duration-300 text-left group"
                    style={{ animationDelay: `${idx * 100}ms` }}
                  >
                    <div className="flex-shrink-0 p-2.5 rounded-xl bg-gradient-to-br from-slate-100 to-slate-200 dark:from-claude-light dark:to-claude-light/50 group-hover:from-primary/20 group-hover:to-primary/30 transition-all duration-300 group-hover:scale-110">
                      {example.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-slate-900 dark:text-claude-text mb-1 group-hover:text-primary transition-colors">
                        {example.title}
                      </div>
                      <div className="text-xs text-slate-600 dark:text-claude-text-secondary line-clamp-2">
                        {example.prompt}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : shouldVirtualize ? (
        /* Virtualized Messages - for long conversations */
        <div className="py-4" style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const message = messages[virtualItem.index];
            return (
              <div
                key={message.message_id}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                <MessageBubble message={message} />
              </div>
            );
          })}

          {/* Scroll anchor */}
          <div ref={messagesEndRef} style={{ position: 'absolute', bottom: 0 }} />
        </div>
      ) : (
        /* Regular Messages - for short conversations */
        <div className="py-4">
          {messages.map((message) => (
            <MessageBubble key={message.message_id} message={message} />
          ))}

          {/* Scroll anchor */}
          <div ref={messagesEndRef} />
        </div>
      )}
    </div>
  );
}
