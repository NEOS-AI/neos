"use client";

import { useEffect, useRef } from "react";
import { useChatStore } from "@/lib/stores/chat-store";
import MessageBubble from "./MessageBubble";
import { Sparkles } from "lucide-react";

export default function MessageList() {
  const { messages, isLoading } = useChatStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="h-full overflow-y-auto">
      {messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-center px-4 py-20">
          <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white text-xl font-bold mb-6 shadow-lg">
            N
          </div>
          <h1 className="text-3xl font-semibold text-claude-text mb-3">
            Welcome to NEOS
          </h1>
          <p className="text-claude-text-secondary max-w-md text-base leading-relaxed mb-12">
            Intelligent Search and Analysis Agent powered by multi-agent AI workflow.
            Ask me anything to get started.
          </p>

          {/* Example Prompts */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 w-full max-w-2xl">
            {examplePrompts.map((prompt, idx) => (
              <button
                key={idx}
                onClick={() => {
                  // This will be implemented in InputBox
                }}
                className="group p-5 bg-claude-dark/50 hover:bg-claude-light/50 border border-claude-border hover:border-claude-border/80 rounded-xl text-left transition-all duration-200"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 text-orange-500">
                    <Sparkles size={18} />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-claude-text mb-1 group-hover:text-white transition-colors">
                      {prompt.title}
                    </div>
                    <div className="text-xs text-claude-text-secondary leading-relaxed">
                      {prompt.description}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div>
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {isLoading && (
            <div className="group w-full">
              <div className="max-w-3xl mx-auto px-6 py-6">
                <div className="flex gap-4 items-start">
                  <div className="flex-shrink-0 mt-1">
                    <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white font-bold text-sm">
                      N
                    </div>
                  </div>
                  <div className="flex-1 min-w-0 pt-0.5">
                    <div className="text-sm font-semibold mb-2 text-claude-text">
                      NEOS
                    </div>
                    <div className="flex gap-1">
                      <div className="w-2 h-2 bg-claude-text-secondary rounded-full typing-dot" />
                      <div className="w-2 h-2 bg-claude-text-secondary rounded-full typing-dot" />
                      <div className="w-2 h-2 bg-claude-text-secondary rounded-full typing-dot" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      <div ref={messagesEndRef} />
    </div>
  );
}

const examplePrompts = [
  {
    title: "Deep Research",
    description: "Conduct comprehensive research on a complex topic with multiple sources",
  },
  {
    title: "Data Analysis",
    description: "Analyze trends, patterns, and insights from your data",
  },
  {
    title: "Web Search",
    description: "Search for real-time information across the web",
  },
  {
    title: "Comparative Analysis",
    description: "Compare multiple sources, products, or viewpoints systematically",
  },
];
