"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useChatStore } from "@/lib/stores/chat-store";
import { PageLoading } from "@/components/chat/LoadingStates";
import { Sparkles, Database, Brain, Code } from "lucide-react";

// New Claude-style components
import GreetingHero from "@/components/home/GreetingHero";
import ChatComposer from "@/components/home/ChatComposer";
import QuickActions from "@/components/home/QuickActions";
import ExampleCards, { ExampleCard } from "@/components/home/ExampleCards";
import TopBar from "@/components/home/TopBar";
import { Mode } from "@/components/home/ModeSelector";

// Example cards data
const exampleCards: ExampleCard[] = [
  {
    icon: Sparkles,
    title: "Deep Research",
    description: "Comprehensive analysis with multi-source research and detailed insights",
    prompt: "Research the latest developments in AI safety",
  },
  {
    icon: Database,
    title: "RAG Query",
    description: "Search through your knowledge base and previous conversations",
    prompt: "Find relevant information from my previous conversations",
  },
  {
    icon: Brain,
    title: "Data Analysis",
    description: "Analyze trends, patterns, and visualize complex datasets",
    prompt: "Analyze trends in renewable energy adoption",
  },
  {
    icon: Code,
    title: "Comparative Analysis",
    description: "Compare different options, frameworks, or solutions side by side",
    prompt: "Compare different machine learning frameworks",
  },
];

// Modes for the mode selector
const modes: Mode[] = [
  { id: "standard", label: "Standard", description: "General conversation and Q&A" },
  { id: "rag", label: "RAG", description: "Search knowledge base" },
  { id: "similarity", label: "Similarity", description: "Find similar content" },
  { id: "deep-research", label: "Deep Research", description: "Comprehensive research" },
];

export default function Home() {
  const router = useRouter();
  const { loadConversations, conversations, createConversation } = useChatStore();
  const [isLoading, setIsLoading] = useState(true);
  const [selectedMode, setSelectedMode] = useState("standard");

  useEffect(() => {
    const initialize = async () => {
      try {
        await loadConversations();
      } catch (error) {
        console.error("Failed to load conversations:", error);
      } finally {
        setIsLoading(false);
      }
    };

    initialize();
  }, [loadConversations]);

  const handleStartNewChat = useCallback(async (prompt?: string) => {
    try {
      await createConversation();

      // Get the newly created conversation ID from the store
      const { currentConversationId } = useChatStore.getState();

      if (currentConversationId) {
        router.push(`/chat/${currentConversationId}`);

        if (prompt) {
          setTimeout(() => {
            useChatStore.getState().sendMessage(prompt);
          }, 100);
        }
      }
    } catch (error) {
      console.error("Failed to create conversation:", error);
    }
  }, [createConversation, router]);

  const handleSendMessage = (message: string) => {
    handleStartNewChat(message);
  };

  const handleExampleCardClick = (card: ExampleCard) => {
    if (card.prompt) {
      handleStartNewChat(card.prompt);
    } else if (card.onClick) {
      card.onClick();
    }
  };

  // Get greeting based on time of day
  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return "Good morning";
    if (hour < 18) return "Good afternoon";
    return "Good evening";
  };

  if (isLoading) {
    return <PageLoading />;
  }

  return (
    <div className="flex min-h-screen bg-bg-canvas">
      {/* Main content area */}
      <main className="flex-1 flex flex-col" role="main">
        {/* Top Bar */}
        <TopBar
          showModeSelector={true}
          modes={modes}
          selectedMode={selectedMode}
          onModeChange={setSelectedMode}
        />

        {/* Main stage */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-6 py-12 space-y-12">
            {/* Greeting Hero */}
            <div className="pt-8">
              <GreetingHero
                greeting={`${getGreeting()}, let's get started`}
              />
            </div>

            {/* Chat Composer */}
            <ChatComposer
              onSend={handleSendMessage}
              placeholder="What can I help you with?"
            />

            {/* Quick Actions */}
            <QuickActions
              actions={[
                {
                  icon: Sparkles,
                  label: "Deep Research",
                  description: "Comprehensive analysis",
                  onClick: () => handleStartNewChat("Start deep research"),
                },
                {
                  icon: Database,
                  label: "RAG Query",
                  description: "Search knowledge base",
                  onClick: () => handleStartNewChat("Search my knowledge base"),
                },
                {
                  icon: Brain,
                  label: "Data Analysis",
                  description: "Analyze data",
                  onClick: () => handleStartNewChat("Help me analyze data"),
                },
                {
                  icon: Code,
                  label: "Code Review",
                  description: "Review code",
                  onClick: () => handleStartNewChat("Review my code"),
                },
              ]}
            />

            {/* Example Cards */}
            <div className="space-y-6">
              <h2 className="text-xl font-semibold text-text-primary">
                Try these examples
              </h2>
              <ExampleCards
                cards={exampleCards.map(card => ({
                  ...card,
                  onClick: () => handleExampleCardClick(card)
                }))}
                columns={2}
              />
            </div>

            {/* Recent Conversations (if any) */}
            {conversations.length > 0 && (
              <div className="space-y-6 pt-8 border-t border-line-soft">
                <h2 className="text-xl font-semibold text-text-primary">
                  Recent conversations
                </h2>
                <div className="grid grid-cols-1 gap-3">
                  {conversations.slice(0, 5).map((conversation) => (
                    <button
                      key={conversation.conversation_id}
                      onClick={() => router.push(`/chat/${conversation.conversation_id}`)}
                      className="
                        flex items-center gap-3 p-4
                        bg-bg-surface border border-line-soft rounded-2xl
                        text-left
                        transition-all duration-200
                        hover:border-brand-accent/30 hover:bg-action-hover hover:shadow-soft
                        focus:outline-none focus:ring-2 focus:ring-brand-accent/50
                      "
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-text-primary truncate">
                          {conversation.title}
                        </div>
                        <div className="text-xs text-text-muted mt-1">
                          {conversation.message_count} messages
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer hint */}
        <div className="py-4 text-center">
          <p className="text-xs text-text-muted">
            NEOS - Intelligent Search and Analysis
          </p>
        </div>
      </main>
    </div>
  );
}
