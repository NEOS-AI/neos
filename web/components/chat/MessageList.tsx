"use client";

import { useEffect, useRef } from "react";
import { useChatStore } from "@/lib/stores/chat-store";
import MessageBubble from "./MessageBubble";

export default function MessageList() {
  const { messages, isLoading } = useChatStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-8">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-20">
            <div className="w-16 h-16 bg-primary rounded-2xl flex items-center justify-center text-white text-2xl font-bold mb-4">
              N
            </div>
            <h2 className="text-2xl font-semibold text-claude-text mb-2">
              Welcome to NEOS
            </h2>
            <p className="text-claude-text-secondary max-w-md">
              Intelligent Search and Analysis Agent powered by multi-agent AI workflow.
              Ask me anything to get started.
            </p>

            {/* Example Prompts */}
            <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-3 w-full max-w-2xl">
              {examplePrompts.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    // This will be implemented in InputBox
                  }}
                  className="p-4 bg-claude-light hover:bg-claude-border rounded-lg text-left transition-colors border border-claude-border"
                >
                  <div className="text-sm font-medium text-claude-text mb-1">
                    {prompt.title}
                  </div>
                  <div className="text-xs text-claude-text-secondary">
                    {prompt.description}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {isLoading && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-white font-semibold flex-shrink-0">
                  N
                </div>
                <div className="flex gap-1 pt-2">
                  <div className="w-2 h-2 bg-claude-text-secondary rounded-full typing-dot" />
                  <div className="w-2 h-2 bg-claude-text-secondary rounded-full typing-dot" />
                  <div className="w-2 h-2 bg-claude-text-secondary rounded-full typing-dot" />
                </div>
              </div>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}

const examplePrompts = [
  {
    title: "Deep Research",
    description: "Conduct comprehensive research on a topic",
  },
  {
    title: "Data Analysis",
    description: "Analyze trends and patterns in data",
  },
  {
    title: "Web Search",
    description: "Search for real-time information online",
  },
  {
    title: "Comparative Analysis",
    description: "Compare multiple sources and viewpoints",
  },
];
