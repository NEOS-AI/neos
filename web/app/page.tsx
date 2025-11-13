"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useChatStore } from "@/lib/stores/chat-store";
import { PageLoading } from "@/components/chat/LoadingStates";
import { Sparkles, Database, Brain, ArrowRight, MessageSquare, Plus } from "lucide-react";

const examplePrompts = [
  {
    icon: <Sparkles className="w-5 h-5" />,
    title: "Deep Research",
    prompt: "Research the latest developments in AI safety",
    color: "from-orange-400 to-amber-600",
  },
  {
    icon: <Database className="w-5 h-5" />,
    title: "Data Analysis",
    prompt: "Analyze trends in renewable energy adoption",
    color: "from-blue-400 to-cyan-600",
  },
  {
    icon: <Brain className="w-5 h-5" />,
    title: "RAG Query",
    prompt: "Find relevant information from my previous conversations",
    color: "from-purple-400 to-pink-600",
  },
  {
    icon: <ArrowRight className="w-5 h-5" />,
    title: "Comparative Analysis",
    prompt: "Compare different machine learning frameworks",
    color: "from-green-400 to-emerald-600",
  },
];

export default function Home() {
  const router = useRouter();
  const { loadConversations, conversations, createConversation } = useChatStore();
  const [isLoading, setIsLoading] = useState(true);

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
      const newConversation = await createConversation();
      if (newConversation?.conversation_id) {
        // Navigate to the new chat
        router.push(`/chat/${newConversation.conversation_id}`);

        // If there's a prompt, send it after navigation
        if (prompt) {
          // We'll send the message after the page loads
          // This will be handled by the chat page
          setTimeout(() => {
            useChatStore.getState().sendMessage(prompt);
          }, 100);
        }
      }
    } catch (error) {
      console.error("Failed to create conversation:", error);
    }
  }, [createConversation, router]);

  const handleConversationClick = (conversationId: string) => {
    router.push(`/chat/${conversationId}`);
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  if (isLoading) {
    return <PageLoading />;
  }

  return (
    <main className="flex min-h-screen flex-col bg-claude-darker">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-6 py-12">
          {/* Hero Section */}
          <div className="text-center space-y-6 mb-12">
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-3xl bg-gradient-to-br from-orange-400 to-amber-600 text-white text-4xl font-bold shadow-2xl">
              N
            </div>
            <h1 className="text-5xl font-bold text-claude-text">
              Welcome to NEOS
            </h1>
            <p className="text-claude-text-secondary text-xl max-w-2xl mx-auto">
              Your intelligent search and analysis agent powered by advanced AI
            </p>

            <button
              onClick={() => handleStartNewChat()}
              className="inline-flex items-center gap-3 px-8 py-4 bg-primary hover:bg-primary-hover text-white rounded-xl transition-all font-medium text-lg shadow-lg hover:shadow-xl"
            >
              <Plus size={24} />
              <span>Start New Chat</span>
            </button>
          </div>

          {/* Example Prompts */}
          <div className="space-y-6 mb-16">
            <h2 className="text-2xl font-semibold text-claude-text text-center">
              Try one of these examples
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {examplePrompts.map((example, idx) => (
                <button
                  key={idx}
                  onClick={() => handleStartNewChat(example.prompt)}
                  className="flex items-start gap-4 p-6 bg-claude-dark border border-claude-border rounded-2xl hover:bg-claude-light hover:border-primary/50 hover:scale-[1.02] transition-all text-left group"
                >
                  <div className={`flex-shrink-0 p-3 rounded-xl bg-gradient-to-br ${example.color} text-white shadow-lg`}>
                    {example.icon}
                  </div>
                  <div className="flex-1 min-w-0 space-y-2">
                    <div className="text-lg font-semibold text-claude-text">
                      {example.title}
                    </div>
                    <div className="text-sm text-claude-text-secondary">
                      {example.prompt}
                    </div>
                  </div>
                  <ArrowRight className="flex-shrink-0 w-5 h-5 text-claude-text-secondary group-hover:text-primary transition-colors" />
                </button>
              ))}
            </div>
          </div>

          {/* Recent Conversations */}
          {conversations.length > 0 && (
            <div className="space-y-6">
              <h2 className="text-2xl font-semibold text-claude-text">
                Recent Conversations
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {conversations.slice(0, 6).map((conversation) => (
                  <button
                    key={conversation.conversation_id}
                    onClick={() => handleConversationClick(conversation.conversation_id)}
                    className="flex items-start gap-3 p-5 bg-claude-dark border border-claude-border rounded-xl hover:bg-claude-light hover:border-primary/50 hover:scale-[1.02] transition-all text-left group"
                  >
                    <MessageSquare
                      size={20}
                      className="flex-shrink-0 text-claude-text-secondary mt-1"
                    />
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="text-base font-medium text-claude-text truncate">
                        {conversation.title}
                      </div>
                      <div className="text-sm text-claude-text-secondary">
                        {formatDate(conversation.updated_at)} · {conversation.message_count} messages
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-claude-border bg-claude-dark py-6">
        <div className="max-w-6xl mx-auto px-6 text-center text-sm text-claude-text-secondary">
          <p>NEOS - Intelligent Search and Analysis</p>
          {conversations.length > 0 && (
            <p className="mt-2">{conversations.length} conversations</p>
          )}
        </div>
      </div>
    </main>
  );
}
