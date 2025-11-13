"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import MessageBubble from "./MessageBubble";
import { useEffect, useRef } from "react";
import { Sparkles, Database, Brain, ArrowRight } from "lucide-react";

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
  // Use selector to properly subscribe to store changes
  const sendMessage = useChatStore((state) => state.sendMessage);
  const settings = useChatStore((state) => state.settings);

  // Compute currentConversation and messages directly from state for proper reactivity
  const currentConversation = useChatStore((state) => {
    const current = state.conversations.find(
      (c) => c.conversation_id === state.currentConversationId
    );
    return current || null;
  });

  const messages = currentConversation?.messages || [];
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Debug logging
  useEffect(() => {
    console.log("[MessageList] Component rendered:", {
      messagesCount: messages.length,
      conversationId: currentConversation?.conversation_id,
      hasConversation: !!currentConversation,
    });
  }, [messages, currentConversation]);

  useEffect(() => {
    console.log("[MessageList] Messages array changed:", {
      count: messages.length,
      messages: messages.map(m => ({
        id: m.message_id.slice(0, 8),
        role: m.role,
        content: m.content.slice(0, 30)
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
    <div className="h-full overflow-y-auto">
      {!currentConversation || messages.length === 0 ? (
        /* Empty State - No conversation or no messages */
        <div className="flex items-center justify-center min-h-full p-8">
          <div className="max-w-2xl text-center space-y-8">
            {/* Logo and Welcome */}
            <div className="space-y-4">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-orange-400 to-amber-600 text-white text-3xl font-bold shadow-lg">
                N
              </div>
              <h1 className="text-3xl font-bold text-claude-text">
                Welcome to NEOS
              </h1>
              <p className="text-claude-text-secondary text-lg">
                Your intelligent search and analysis agent
              </p>
            </div>

            {/* Current Mode Info */}
            <div className="inline-flex items-center gap-2 px-4 py-2 bg-claude-dark border border-claude-border rounded-lg">
              {settings.mode === "rag" && (
                <>
                  <Database className="w-4 h-4 text-blue-400" />
                  <span className="text-sm text-claude-text">
                    RAG Mode - Context-aware responses
                  </span>
                </>
              )}
              {settings.mode === "similarity" && (
                <>
                  <Brain className="w-4 h-4 text-purple-400" />
                  <span className="text-sm text-claude-text">
                    Similarity Mode - Intelligent context retrieval
                  </span>
                </>
              )}
              {settings.mode === "standard" && (
                <>
                  <Sparkles className="w-4 h-4 text-orange-400" />
                  <span className="text-sm text-claude-text">
                    Standard Mode - Direct conversation
                  </span>
                </>
              )}
            </div>

            {/* Example Prompts */}
            <div className="space-y-3">
              <p className="text-sm text-claude-text-secondary">
                Try one of these examples:
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {examplePrompts.map((example, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleExampleClick(example.prompt)}
                    className="flex items-center gap-3 p-4 bg-claude-dark border border-claude-border rounded-xl hover:bg-claude-light hover:border-primary/50 transition-all text-left group"
                  >
                    <div className="flex-shrink-0 p-2 rounded-lg bg-claude-light group-hover:bg-primary/20 transition-colors">
                      {example.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-claude-text mb-1">
                        {example.title}
                      </div>
                      <div className="text-xs text-claude-text-secondary line-clamp-2">
                        {example.prompt}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Messages */
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
