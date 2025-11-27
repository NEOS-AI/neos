"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useChatStore } from "@/lib/stores/chat-store";
import { PageLoading } from "@/components/chat/LoadingStates";
import { Sparkles, Database, Brain, Code } from "lucide-react";

// New Claude-style components
import Sidebar from "@/components/home/Sidebar";
import GreetingHero from "@/components/home/GreetingHero";
import ChatComposer from "@/components/home/ChatComposer";
import QuickActions from "@/components/home/QuickActions";
import TopBar from "@/components/home/TopBar";
import { Mode } from "@/components/home/ModeSelector";


// Modes for the mode selector
const modes: Mode[] = [
  { id: "standard", label: "Standard", description: "General conversation and Q&A" },
  { id: "rag", label: "RAG", description: "Search knowledge base" },
  { id: "similarity", label: "Similarity", description: "Find similar content" },
  { id: "deep_research", label: "Deep Research", description: "Comprehensive research" },
];

export default function Home() {
  const router = useRouter();
  const { loadConversations, conversations, createConversation, updateSettings } = useChatStore();
  const [isLoading, setIsLoading] = useState(true);
  const [selectedMode, setSelectedMode] = useState("standard");
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

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

  // Handle starting a new chat with the selected mode
  const handleStartNewChat = useCallback(async (prompt?: string) => {
    try {
      // CRITICAL: Update settings mode BEFORE creating conversation
      // This ensures sendMessage uses the correct mode
      updateSettings({ mode: selectedMode as any });

      // Create conversation with the selected mode
      await createConversation(undefined, undefined, selectedMode);

      // Get the newly created conversation ID from the store
      const { currentConversationId } = useChatStore.getState();

      if (currentConversationId) {
        // If there's a prompt, pass it as a query parameter
        // The chat page will send it after initialization is complete
        if (prompt) {
          router.push(`/chat/${currentConversationId}?initialMessage=${encodeURIComponent(prompt)}`);
        } else {
          router.push(`/chat/${currentConversationId}`);
        }
      }
    } catch (error) {
      console.error("Failed to create conversation:", error);
    }
  }, [createConversation, router, selectedMode, updateSettings]);

  const handleSendMessage = (message: string) => {
    handleStartNewChat(message);
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
      {/* Skip to main content link for accessibility */}
      <a
        href="#main-content"
        className="
          sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4
          z-[100] px-4 py-2 bg-brand-accent text-white rounded-xl
          focus:outline-none focus:ring-2 focus:ring-brand-accent/50
        "
      >
        Skip to main content
      </a>

      {/* Sidebar */}
      <Sidebar
        isMobileOpen={isSidebarOpen}
        onMobileClose={() => setIsSidebarOpen(false)}
      />

      {/* Main content area */}
      <main id="main-content" className="flex-1 flex flex-col" role="main">
        {/* Top Bar */}
        <TopBar
          showModeSelector={true}
          modes={modes}
          selectedMode={selectedMode}
          onModeChange={setSelectedMode}
          onMenuClick={() => setIsSidebarOpen(true)}
        />

        {/* Main stage */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-[860px] mx-auto px-6 py-16">
            {/* Greeting Hero */}
            <div className="pt-12">
              <GreetingHero
                greeting={`${getGreeting()}, let's get started`}
              />
            </div>

            {/* Chat Composer */}
            <div className="mt-10">
              <ChatComposer
                onSend={handleSendMessage}
                placeholder="What can I help you with?"
              />
            </div>

            {/* Recent Conversations (if any) */}
            {conversations.length > 0 && (
              <div className="mt-16 space-y-6 pt-12 border-t border-line-soft">
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
